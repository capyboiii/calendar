"""Ghép trang lịch đã render vào ảnh mockup (ảnh preview listing). Cách ghép đã được duyệt "chuẩn" 25/09/2026.

Pipeline gọi previews(concept_dir) sau bước render -> render/previews/*.png (PREVIEWS: 5 mockup theo thứ tự listing).
Chạy tay:
    python -m calforge.render.mockups <tên mockup> <concept>/render/printify <ảnh ra.png>
    python -m calforge.render.mockups --list

Mỗi mockup khai báo các tờ giấy trong ảnh (MOCKUPS bên dưới):
- kind "spread": tờ lịch mở - trang tranh ở trên, trang lịch ở dưới, lò xo ở giữa. Chỗ nối = đường GIỮA 2 hàng
  mắt lò xo (dò tự động), mỗi nửa một phép phối cảnh riêng, mép trái/phải dò riêng cho từng trang.
- kind "page": một trang tranh đơn (lịch để bàn, bìa...).
Chung cho mọi loại: ghép cả lề tràn (bleed) rồi cắt theo mép; thu nhỏ INTER_AREA trước khi bóp phối cảnh,
làm việc ở độ phân giải gấp SCALE lần mockup, làm nét nhẹ; độ sáng mockup NHÂN vào (multiply, chặn <= 1.0)
để giữ bóng giấy, lò xo, lỗ treo mà không bị quầng trắng.
Mép giấy: "paper" = cắt theo hình giấy thật (nền khác màu giấy rõ rệt); "geo" = theo mép hình học đã đo
(nền sáng gần bằng giấy, vd tường trắng).
Mockup mới: đo góc/mép trang bằng Hough (cv2.HoughLinesP trên Canny) hoặc dò độ sáng giấy, rồi thêm vào MOCKUPS.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parents[2] / "data" / "mockups"   # ảnh mockup gốc
SCALE = 2
BLEED = 38        # lề tràn file in (37.5 px @300dpi)


def box(tl, tr, br, bl):
    """Khai báo tờ giấy bằng 4 góc (tl, tr, br, bl)."""
    return dict(top=[tl, tr], right=[tr, br], bottom=[bl, br], left=[tl, bl])


MOCKUPS = {
    # bìa lịch treo, lò xo ở mép trên, khe treo giữa, lỗ dưới (trang mockup hơi cao hơn 11x8.5 ~8%: kéo vừa khung)
    "front_cover_spiral": dict(file="front_cover_spiral.webp", edges="geo", metal=30, metal_thr=18, sheets=[
        dict(source="front_cover", kind="page", lines=box((168, 244), (1083.5, 244), (1083.5, 1011), (168, 1011)),
             cutouts=[(626, 256, 16)], cutout_thr=22,
             through=[(627, 985, 9)]),                      # lỗ dưới: thủng hẳn, thấy nền sau
    ]),
    # 3 tờ lịch mở nằm nghiêng trên bàn (mép đo bằng Hough, nhiều đoạn thì fit chung); tờ 3 đè lên 2 tờ kia
    "three_open_spreads": dict(file="three_open_spreads.webp", edges="paper", sheets=[
        dict(month=1, kind="spread", lines=dict(
            top=[(189, 94), (614, 235)], bottom=[(0, 766), (381, 907), (1, 769), (377, 909)],
            left=[(187, 94), (50, 509), (58, 484), (0, 651)],
            right=[(616, 236), (496, 596), (445, 722), (378, 909)])),
        dict(month=2, kind="spread", lines=dict(
            top=[(655, 131), (1093, 5)], bottom=[(904, 778), (1253, 672), (908, 781), (1252, 676)],
            left=[(653, 133), (782, 570)], right=[(1095, 5), (1252, 552), (1100, 8), (1253, 542)])),
        dict(month=3, kind="spread", lines=dict(
            top=[(439, 604), (782, 571)], bottom=[(494, 1235), (948, 1186), (498, 1238), (946, 1189)],
            left=[(447, 721), (492, 1234)], right=[(882, 563), (945, 1189)])),
    ]),
    # 1 tờ lịch mở nhìn thẳng trên nền be
    "open_spread_flat": dict(file="open_spread_flat.webp", seam="band", metal=22, metal_thr=18, edges="paper", sheets=[
        dict(month=1, kind="spread", lines=box((313, 114), (940, 114), (940, 1136), (313, 1136)),
             cutouts=[(626, 130, 11), (626, 1120, 11)], cutout_thr=18),
    ]),
    # 1 tờ lịch mở treo tường phòng khách (tường sáng gần bằng giấy -> mép hình học)
    "wall_spread": dict(file="wall_spread.webp", seam="band", metal=10, metal_thr=32, edges="geo", sheets=[
        dict(month=2, kind="spread", lines=box((528, 197), (872, 197), (872, 735), (528, 735))),
    ]),
    # treo tường, tay đang lật trang dưới: tranh T1 trên, lịch T1 trên trang cong, lịch T2 lộ ra phía sau
    "wall_page_turn": dict(file="wall_page_turn.webp", curl=True, month=1,
                           sheets=[dict(kind="curl", month=1)],         # dùng: tranh T1, lịch T1, lịch T2
                           top=[(426, 127), (922, 122), (922, 533), (426, 533)],
                           front=[(426, 533), (923, 533), (923, 946), (410, 946)],
                           back=[(426, 533), (923, 533), (922, 949), (426, 930)]),
    # ---- lịch grid in sẵn (products.wall_premade): trang grid đã in sẵn trong mockup, chỉ ghép tranh tháng
    # vào trang trống phía trên lò xo (lò xo ở MÉP DƯỚI trang tranh: metal_edge="bottom"). Mép đo bằng gradient
    # (mép giấy) + tâm dải lò xo, 28/09/2026.
    "premade_wall_straight": dict(file="premade_wall_straight.webp", edges="geo", sheets=[
        dict(month=1, kind="page", lines=box((331.0, 91.7), (943.0, 89.6), (943.0, 581.6), (331.0, 581.3)),
             metal=16, metal_thr=18, metal_edge="bottom", through=[(631, 100, 11)]),      # đinh treo đồng
    ]),
    "premade_wall_angled": dict(file="premade_wall_angled.webp", edges="geo", sheets=[
        dict(month=9, kind="page", lines=box((372.4, 79.3), (879.5, 140.7), (881.8, 586.0), (371.6, 580.6)),
             metal=16, metal_thr=18, metal_edge="bottom", through=[(636, 117, 9)]),
    ]),
    "premade_three_spreads": dict(file="premade_three_spreads.webp", edges="geo", grow=1.2, sheets=[
        dict(month=1, kind="page", lines=box((244.8, 177.6), (597.8, 306.7), (493.5, 589.2), (141.3, 460.4)),
             metal=14, metal_thr=18, metal_edge="bottom"),
        dict(month=3, kind="page", lines=box((652.1, 188.1), (1015.0, 57.8), (1114.2, 344.8), (751.6, 473.8)),
             metal=14, metal_thr=18, metal_edge="bottom"),
        dict(month=2, kind="page", metal=14, metal_thr=18, metal_edge="bottom",          # tờ tháng 2 nằm trên cùng
             lines=dict(top=[(500, 608), (530, 605), (560, 602), (590, 599), (620, 597), (650, 594), (680, 591),
                             (710, 588), (740, 585), (770, 583)],                         # đo tay từng cột
                        right=[(818.7, 582.5), (845.5, 864.2)], bottom=[(478.7, 898.9), (845.5, 864.2)],
                        left=[(456.7, 610.3), (478.7, 898.9)])),
    ]),
    # 2 cuốn gập (bìa trước + trang grid tháng 1), lò xo mép trên: mép trên = hàng lỗ đột (dời lên 5px cho phủ
    # kín giấy). Mép "geo": nền sáng gần bằng giấy, cắt theo màu giấy sẽ để lại viền trắng.
    # Mép trên = mép giấy thật (vạch sáng ngay trên hàng lỗ đột, dò theo bước nhảy độ sáng từng cột): tranh in tới sát
    # mép; mỗi vòng dây = 1 cột từ mép giấy xuống đáy lỗ đột, giữ nguyên mockup (metal_mode="loops"); khe giữa các
    # vòng in tranh; nền phía trên mép không bị phủ.
    "premade_two_closed": dict(file="premade_two_closed.webp", edges="geo", grow=0.6, metal=14, metal_mode="loops",
                               sheets=[
        dict(source="front_cover", kind="page",
             lines=dict(top=[(121.0, 222.8), (658.8, 139.0)], right=[(658.8, 148.1), (729.7, 574.1)],
                        bottom=[(192.5, 660.4), (729.7, 574.1)], left=[(121.0, 232.2), (192.5, 660.4)])),
        dict(source="m01_grid", kind="page",
             lines=dict(top=[(575.1, 640.9), (1124.9, 667.1)], right=[(1124.9, 664.1), (1107.5, 1099.8)],
                        bottom=[(553.8, 1069.0), (1107.5, 1099.8)], left=[(575.1, 650.9), (553.8, 1069.0)])),
    ]),
    # 2 tờ lịch mở treo tường (chỉ dùng cho "AI gen mockup"): tờ trái tháng 1, tờ phải tháng 2. Tường sáng gần bằng
    # giấy -> mép hình học (đo bằng gradient), lỗ treo trên/dưới đo trực tiếp, 02/10/2026.
    "two_wall_spreads": dict(file="two_wall_spreads.webp", seam="band", metal=9, metal_thr=10, edges="geo", sheets=[
        dict(month=1, kind="spread", lines=box((177.5, 52.5), (616, 52.5), (616, 723), (177.5, 723)),
             through=[(397, 65.5, 5.5), (396, 709.5, 5.5)]),
        dict(month=2, kind="spread", lines=box((672.5, 342.5), (1112, 342.5), (1112, 1009), (672.5, 1009)),
             through=[(887.5, 354.5, 5.5), (887.5, 995.5, 5.5)]),
    ]),
    # 3 cuốn nằm trên nền xanh (ảnh 2000px, chỉ dùng cho "AI gen mockup"): bìa, trang lịch tháng 4 (lò xo mép trên),
    # tranh tháng 4 (lò xo mép dưới). Góc đo theo bao lồi mặt giấy, tâm lỗ treo đo trực tiếp, 02/10/2026.
    "three_books": dict(file="three_books.webp", edges="geo", metal=46, metal_thr=18, sheets=[
        dict(source="front_cover", kind="page", lines=box((81, 348), (868, 236), (960, 843), (145, 966)),
             through=[(554.2, 879.4, 12)]),
        dict(source="m04_grid", kind="page", lines=box((1115, 286), (1926, 391), (1861, 1011), (1023, 888)),
             through=[(1432.1, 923.2, 12)]),
        dict(source="m04_month", kind="page", metal_edge="bottom", through=[(1017.5, 1069.5, 11)],
             lines=box((608, 1010), (1447, 1088), (1398, 1733), (528, 1643))),
    ]),
}


def fit(points):
    vx, vy, x0, y0 = cv2.fitLine(np.float32(points), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
    return np.float32([x0, y0]), np.float32([vx, vy])


def cross(l1, l2):
    (p1, d1), (p2, d2) = l1, l2
    t = np.linalg.solve(np.array([[d1[0], -d2[0]], [d1[1], -d2[1]]], np.float32), p2 - p1)
    return p1 + d1 * t[0]


def signed(pts, line):
    p, d = line
    return (pts[:, 0] - p[0]) * -d[1] + (pts[:, 1] - p[1]) * d[0]


def poly_mask(q, shape, erode=0):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.round(q).astype(np.int32)], 255)
    return cv2.erode(m, np.ones((erode, erode), np.uint8)) if erode else m


def _loop_columns(g0: np.ndarray, quad: np.ndarray, bottom: bool, depth: float, shape) -> np.ndarray:
    """Mặt nạ các vòng lò xo nằm trên mặt giấy (ở độ phân giải SCALE). Mỗi lỗ đột (đốm tối gần mép lò xo) sinh 1 cột:
    từ mép giấy tới đáy lỗ, rộng bằng lỗ (+1px). Trong cột giữ nguyên mockup (dây kim loại đặc + lỗ); ngoài cột là
    giấy -> in tranh. Tránh cắt theo ngưỡng màu, vốn để lại cục giấy trắng giữa các vòng dây."""
    a0, a1, inner = (quad[3], quad[2], quad[0]) if bottom else (quad[0], quad[1], quad[3])
    d = (a1 - a0) / np.linalg.norm(a1 - a0)
    n = np.float32([-d[1], d[0]])
    if np.dot(inner - a0, n) < 0:
        n = -n
    ys, xs = np.mgrid[0:g0.shape[0], 0:g0.shape[1]]
    along = (xs - a0[0]) * d[0] + (ys - a0[1]) * d[1]
    inward = (xs - a0[0]) * n[0] + (ys - a0[1]) * n[1]
    L = float(np.linalg.norm(a1 - a0))
    band = (inward > -2) & (inward < depth) & (along > -4) & (along < L + 4)
    local = cv2.medianBlur(g0, 21).astype(np.float32)
    dark = ((local - g0.astype(np.float32) > 60) & band).astype(np.uint8)
    cnt, lab, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    mask = np.zeros(shape, np.uint8)
    for i in range(1, cnt):
        if not 4 <= stats[i, cv2.CC_STAT_AREA] <= 200:
            continue
        k = lab == i
        u, v = along[k], inward[k]
        u0, u1, v1 = float(u.min()) - 1.0, float(u.max()) + 1.0, float(v.max()) + 0.8
        corners = [a0 + d * u0 + n * -1.5, a0 + d * u1 + n * -1.5, a0 + d * u1 + n * v1, a0 + d * u0 + n * v1]
        cv2.fillPoly(mask, [np.round(np.float32(corners) * SCALE + (SCALE - 1) / 2).astype(np.int32)], 255)
    return cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), 0.8)


def render(name: str, pages: Path, out_path: Path, debug: bool = False) -> None:
    cfg = MOCKUPS[name]
    if cfg.get("curl"):
        return render_curl(cfg, pages, out_path)
    sheets = cfg["sheets"]
    mock0 = cv2.imread(str(HERE / cfg["file"]), cv2.IMREAD_COLOR)
    g0 = cv2.cvtColor(mock0, cv2.COLOR_BGR2GRAY)
    H0, W0 = g0.shape
    n = len(sheets)
    lines = [{s: fit(v) for s, v in sh["lines"].items()} for sh in sheets]
    if cfg.get("grow"):                                    # nới mép ra ngoài vài px: hết vệt giấy mảnh ở mép
        for sh, L in zip(sheets, lines):
            pts = np.float32([p for v in sh["lines"].values() for p in v])
            center = pts.mean(axis=0)
            for side, (p0, d0) in L.items():
                nrm = np.float32([-d0[1], d0[0]])
                if np.dot(center - p0, nrm) > 0:
                    nrm = -nrm
                L[side] = (p0 + nrm * cfg["grow"], d0)
    quads = [np.float32([cross(L["left"], L["top"]), cross(L["top"], L["right"]),
                         cross(L["right"], L["bottom"]), cross(L["bottom"], L["left"])]) for L in lines]

    def later_mask(k, dilate=0):
        m = np.zeros(g0.shape, np.uint8)
        for j in range(k + 1, n):                          # tờ vẽ sau đè lên tờ k
            m |= poly_mask(quads[j], g0.shape)
        return cv2.dilate(m, np.ones((dilate, dilate), np.uint8)) if dilate else m

    # ---- chỗ nối của tờ mở = đường giữa 2 hàng mắt lò xo
    seams, rows = {}, {}
    for k, sh in enumerate(sheets):
        if sh["kind"] != "spread":
            continue
        vis = poly_mask(quads[k], g0.shape, erode=7)
        vis[later_mask(k) > 0] = 0
        paper_lvl = float(np.median(g0[vis > 0]))
        dark = ((g0 < min(150, paper_lvl - 60)) & (vis > 0)).astype(np.uint8)
        cnt, _lab, stats, cents = cv2.connectedComponentsWithStats(dark, connectivity=8)
        c = np.float32([cents[i] for i in range(1, cnt) if 2 <= stats[i, cv2.CC_STAT_AREA] <= 300])
        line = fit(c)
        for _ in range(3):                                   # bỏ lỗ treo trên/dưới
            c = c[np.abs(signed(c, line)) < 25]
            line = fit(c)
        sd = signed(c, line)
        art_side = np.sign(signed(np.float32([quads[k][0]]), line)[0])   # phía góc trên-trái = trang tranh
        a, b = c[sd * art_side > 0], c[sd * art_side <= 0]
        if cfg.get("seam") == "band":
            # tâm CẢ dải lò xo (giữa mép ngoài 2 hàng lỗ): đúng hơn khi dây lò xo xám nằm giữa 2 hàng
            ys, xs = np.where(dark > 0)
            px = np.float32(np.column_stack([xs, ys]))
            dd = signed(px, line)
            px = px[np.abs(dd) < 25]
            lo, hi = np.percentile(signed(px, line), [3, 97])
            p0, d0 = line
            seams[k], rows[k] = (p0 + np.float32([-d0[1], d0[0]]) * float((lo + hi) / 2), d0), ()
        elif len(a) >= 5 and len(b) >= 5:
            up_row, lo_row = fit(a), fit(b)
            d = up_row[1] if np.dot(up_row[1], lo_row[1]) > 0 else -up_row[1]
            d = (d + lo_row[1]) / np.linalg.norm(d + lo_row[1])
            mid = (up_row[0] + cross(lo_row, (up_row[0], np.float32([-up_row[1][1], up_row[1][0]])))) / 2
            seams[k], rows[k] = (np.float32(mid), np.float32(d)), (up_row, lo_row)
        else:                                                # chỉ thấy 1 hàng: lấy đường tâm chung
            seams[k], rows[k] = line, ()

    # ---- dò lại mép trái/phải riêng cho từng trang (±5px quanh đường đã đo)
    g0f = cv2.GaussianBlur(g0.astype(np.float32), (3, 3), 0)
    gx0, gy0 = cv2.Sobel(g0f, cv2.CV_32F, 1, 0), cv2.Sobel(g0f, cv2.CV_32F, 0, 1)

    def refine_side(k, line, a, b, search=5):
        p, d = line
        nrm = np.float32([-d[1], d[0]])
        later = later_mask(k, dilate=9)
        pts = []
        for t in np.linspace(0.06, 0.94, 40):
            base = a + (b - a) * t
            base = p + d * np.dot(base - p, d)
            vals = []
            for sft in range(-search, search + 1):
                x, y = base + nrm * sft
                xi, yi = int(round(x)), int(round(y))
                if not (2 <= xi < W0 - 2 and 2 <= yi < H0 - 2) or later[yi, xi]:
                    vals = []
                    break
                vals.append(abs(gx0[yi, xi] * nrm[0] + gy0[yi, xi] * nrm[1]))
            if len(vals) != 2 * search + 1:
                continue
            i = int(np.argmax(vals))
            if vals[i] < 25 or i in (0, len(vals) - 1):
                continue
            l, c0, r = vals[i - 1], vals[i], vals[i + 1]       # nội suy parabol -> dưới 1 px
            off = 0.5 * (l - r) / (l - 2 * c0 + r) if (l - 2 * c0 + r) != 0 else 0
            pts.append(base + nrm * (i - search + off))
        return fit(np.float32(pts)) if len(pts) >= 8 else line

    mock = cv2.resize(mock0, (W0 * SCALE, H0 * SCALE), interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(mock, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = gray.shape
    up = lambda q: np.float32(q) * SCALE + (SCALE - 1) / 2
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    g_sharp = np.clip(gray * 1.6 - cv2.GaussianBlur(gray, (0, 0), 1.2) * 0.6, 0, 255)

    def warp_full(name_png, quad):
        """Ghép CẢ trang (kèm lề tràn) sao cho khung trim rơi đúng tứ giác đích."""
        img = cv2.imread(str(pages / f"{name_png}.png"), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(pages / f"{name_png}.png")
        ih, iw = img.shape[:2]
        edge = max(np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[2] - quad[3]))
        sc = edge * 1.25 / (iw - 2 * BLEED)
        small = cv2.resize(img, (round(iw * sc), round(ih * sc)), interpolation=cv2.INTER_AREA)
        b, tw, th = BLEED * sc, (iw - 2 * BLEED) * sc, (ih - 2 * BLEED) * sc
        src = np.float32([[b, b], [b + tw, b], [b + tw, b + th], [b, b + th]])
        M = cv2.getPerspectiveTransform(src, np.float32(quad))
        return cv2.warpPerspective(small, M, (W, H), flags=cv2.INTER_CUBIC,
                                   borderMode=cv2.BORDER_REPLICATE).astype(np.float32)

    out = mock.astype(np.float32)
    for k, sh in enumerate(sheets):
        L, month = lines[k], sh.get("month", 0)
        tl, tr, br, bl = quads[k]
        if sh["kind"] == "spread":
            seam = seams[k]
            sl, sr = cross(L["left"], seam), cross(seam, L["right"])
            lt, rt = refine_side(k, L["left"], tl, sl), refine_side(k, L["right"], tr, sr)
            lb, rb = refine_side(k, L["left"], sl, bl), refine_side(k, L["right"], sr, br)
            top_q = up([cross(lt, L["top"]), cross(L["top"], rt), cross(rt, seam), cross(seam, lt)])
            bot_q = up([cross(seam, lb), cross(rb, seam), cross(rb, L["bottom"]), cross(L["bottom"], lb)])
            wa, wg = warp_full(f"m{month:02d}_month", top_q), warp_full(f"m{month:02d}_grid", bot_q)
            sp, sdir = up([seam[0]])[0], seam[1]
            dist = (xx - sp[0]) * -sdir[1] + (yy - sp[1]) * sdir[0]
            art_sign = np.sign((top_q[0][0] - sp[0]) * -sdir[1] + (top_q[0][1] - sp[1]) * sdir[0])
            m_art = np.clip(0.5 + dist * art_sign, 0, 1)[..., None]
            layer = wa * m_art + wg * (1 - m_art)
            outline = np.float32([top_q[0], top_q[1], top_q[2], bot_q[1], bot_q[2], bot_q[3], bot_q[0], top_q[3]])
        else:
            outline = up(quads[k])
            layer = warp_full(sh.get("source") or f"m{month:02d}_month", outline)
        poly = np.zeros((H, W), np.uint8)
        cv2.fillPoly(poly, [np.round(outline).astype(np.int32)], 255)
        geo = cv2.GaussianBlur(poly.astype(np.float32) / 255, (0, 0), 0.7)
        if cfg["edges"] == "paper":
            inner = cv2.erode(poly, np.ones((10 * SCALE, 10 * SCALE), np.uint8)) > 0
            outer = cv2.dilate(poly, np.ones((6 * SCALE, 6 * SCALE), np.uint8)) > 0
            others = np.zeros((H, W), np.uint8)
            for j in range(n):
                if j != k:
                    cv2.fillPoly(others, [np.round(up(quads[j])).astype(np.int32)], 255)
            paper_soft = np.clip((gray - 236) / 8, 0, 1)
            band = np.where(others > 0, geo, paper_soft)
            alpha = np.where(inner, 1.0, np.where(outer, band, 0.0))
        elif sh.get("paper_sides"):
            # cắt theo giấy thật chỉ ở các cạnh khai báo; cạnh còn lại theo mép hình học
            inner = cv2.erode(poly, np.ones((10 * SCALE, 10 * SCALE), np.uint8)) > 0
            outer = cv2.dilate(poly, np.ones((6 * SCALE, 6 * SCALE), np.uint8)) > 0
            q = np.float32(outline)
            sides = {"top": (q[0], q[1]), "right": (q[1], q[2]), "bottom": (q[3], q[2]), "left": (q[0], q[3])}
            dist = {}
            for nm, (a0, a1) in sides.items():
                d = (a1 - a0) / np.linalg.norm(a1 - a0)
                dist[nm] = np.abs((xx - a0[0]) * -d[1] + (yy - a0[1]) * d[0])
            nearest = np.argmin(np.stack([dist[nm] for nm in sides]), axis=0)
            use_paper = np.isin(nearest, [list(sides).index(nm) for nm in sh["paper_sides"]])
            paper_soft = np.clip((gray - 236) / 8, 0, 1)
            band = np.where(use_paper, paper_soft, geo)
            alpha = np.where(inner, 1.0, np.where(outer, band, 0.0))
        else:
            alpha = geo
        sheet = poly_mask(up(quads[k]), (H, W), erode=4 * SCALE) > 0
        paper = float(np.percentile(gray[sheet], 95))
        # lỗ khoét (khe treo...): trong vòng khai báo, chỗ mockup tối hẳn so với giấy là lỗ -> bỏ tranh
        for cx, cy, r in sh.get("cutouts", ()):
            ring = np.zeros((H, W), np.uint8)
            cv2.circle(ring, tuple(np.int32(up([(cx, cy)])[0])), int(r * SCALE), 255, -1)
            hole = np.clip((paper - sh.get("cutout_thr", 50) - cv2.GaussianBlur(gray, (0, 0), 0.8)) / 15, 0, 1)                 * (ring > 0)
            alpha = alpha * (1 - hole)
        # lò xo sắt nằm ĐÈ lên giấy: trong dải lò xo, chỗ mockup khác hẳn màu giấy là sắt/lỗ -> giữ nguyên
        highlight = None
        if sh.get("metal") or cfg.get("metal"):
            depth = (sh.get("metal") or cfg.get("metal")) * SCALE
            if sh["kind"] == "spread":
                sp, sdir = up([seams[k][0]])[0], seams[k][1]
                near = np.abs((xx - sp[0]) * -sdir[1] + (yy - sp[1]) * sdir[0]) < depth
            else:
                # lò xo ở mép trên trang (mặc định) hoặc mép dưới (trang tranh của tờ lịch mở, metal_edge="bottom")
                e0, e1, inward = (3, 2, 0) if sh.get("metal_edge") == "bottom" else (0, 1, 3)
                a0, a1 = np.float32(outline[e0]), np.float32(outline[e1])
                d = (a1 - a0) / np.linalg.norm(a1 - a0)
                below = (xx - a0[0]) * -d[1] + (yy - a0[1]) * d[0]
                below = below * np.sign(np.dot(np.float32(outline[inward]) - a0, np.float32([-d[1], d[0]])))
                near = (below > -4 * SCALE) & (below < depth)
            local_paper = cv2.medianBlur(np.clip(gray, 0, 255).astype(np.uint8), 31).astype(np.float32)
            # chỉ chỗ TỐI hơn giấy (sắt, lỗ); vệt sáng quanh lỗ đột là giấy -> vẫn phủ tranh
            darker = np.maximum(local_paper, paper - 6) - cv2.GaussianBlur(gray, (0, 0), 0.8)
            thr = sh.get("metal_thr", cfg.get("metal_thr", 6))    # bóng nhạt của dây < thr: vẫn phủ tranh
            if (sh.get("metal_mode") or cfg.get("metal_mode")) == "loops":
                cols = _loop_columns(g0, np.float32(outline) / SCALE, sh.get("metal_edge") == "bottom",
                                     (sh.get("metal") or cfg.get("metal")), (H, W))
                # trong cột: sợi dây = viền xám TỐI hơn giấy (lấp lõi trắng giữa 2 viền bằng đóng hình thái), lỗ = tối
                # hẳn. Giấy sáng quanh lỗ / giữa 2 sợi -> in tranh (giấy thật in tràn tới mép lỗ).
                g_bl = cv2.GaussianBlur(gray, (0, 0), 0.6)
                wire = np.clip((paper - g_bl - 35) / 12, 0, 1)                 # bóng dây (tối <35) vẫn in tranh
                wire = cv2.morphologyEx(wire, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
                wire = wire * np.clip((paper + 2 - g_bl) / 6, 0, 1)            # viền sáng quanh lỗ = giấy -> in tranh
                metal = cols * cv2.GaussianBlur(wire, (0, 0), 0.5)
            else:
                metal = cv2.GaussianBlur(np.clip((darker - thr) / 12, 0, 1) * near, (0, 0), 0.6)
            alpha = alpha * (1 - metal)
        for cx, cy, r in sh.get("through", ()):                  # lỗ thủng khai báo tay: bỏ tranh cả vòng tròn
            ring = np.zeros((H, W), np.float32)
            cv2.circle(ring, tuple(np.int32(up([(cx, cy)])[0])), int(r * SCALE), 1.0, -1, cv2.LINE_AA)
            alpha = alpha * (1 - ring)
        # lỗ treo / lỗ đột ở bất kỳ đâu trên trang: chỗ mockup tối hẳn so với giấy quanh nó -> giữ nguyên mockup
        local = cv2.medianBlur(np.clip(gray, 0, 255).astype(np.uint8), 41).astype(np.float32)
        holes = np.clip((local - cv2.GaussianBlur(gray, (0, 0), 0.8) - 28) / 14, 0, 1)
        holes = holes * (cv2.erode(poly, np.ones((6, 6), np.uint8)) > 0)
        alpha = alpha * (1 - cv2.GaussianBlur(holes, (0, 0), 0.7))
        alpha = alpha.astype(np.float32)[..., None]
        blur = cv2.GaussianBlur(layer, (0, 0), 1.0)
        layer = np.clip(layer * 1.45 - blur * 0.45, 0, 255)
        shade = np.clip(g_sharp / paper, 0, 1.0)[..., None]
        printed = layer * shade
        if highlight is not None:
            printed = printed + (255 - printed) * highlight
        out = out * (1 - alpha) + printed * alpha

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _save(out_path, out)
    if not debug:
        return
    dbg = mock0.copy()                                        # ảnh kiểm tra: mép + lò xo đã dò
    for k in range(n):
        cv2.polylines(dbg, [np.round(quads[k]).astype(np.int32)], True, (0, 0, 255), 1)
        for rp, rd in rows.get(k, ()):
            cv2.line(dbg, tuple(np.int32(rp - rd * 400)), tuple(np.int32(rp + rd * 400)), (0, 160, 0), 1)
        if k in seams:
            p, d = seams[k]
            cv2.line(dbg, tuple(np.int32(p - d * 400)), tuple(np.int32(p + d * 400)), (255, 0, 0), 1)
    cv2.imwrite(str(out_path.with_name(out_path.stem + "_debug.png")), dbg)


def render_curl(cfg: dict, pages: Path, out_path: Path) -> None:
    """Lịch treo tường đang lật trang dưới: tranh tháng N ở trên lò xo, lịch tháng N trên phần trang đang cong,
    lịch tháng N+1 ở phần trang sau lộ ra dưới đường cong; bàn tay (màu da) luôn nằm trên cùng.
    Đường cong dò tự động theo từng cột: chỗ đầu tiên dưới lò xo mà mockup tối hẳn so với giấy."""
    mock0 = cv2.imread(str(HERE / cfg["file"]), cv2.IMREAD_COLOR)
    g0 = cv2.cvtColor(mock0, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H0, W0 = g0.shape
    top_q, front_q, back_q = (np.float32(cfg[k]) for k in ("top", "front", "back"))
    seam_y = float(top_q[3][1])
    xs, ys = [], []
    for x in range(int(front_q[0][0]) + 4, int(front_q[1][0]) - 1):   # chỉ dò bên trong trang
        col = g0[int(seam_y) + 40:int(front_q[2][1]) + 6, x]
        idx = np.where(col < 226)[0]
        if len(idx):
            xs.append(x); ys.append(seam_y + 40 + idx[0])
    ys = cv2.GaussianBlur(np.float32(ys).reshape(-1, 1), (1, 9), 0).ravel()   # làm mượt đường cong
    S = SCALE
    mock = cv2.resize(mock0, (W0 * S, H0 * S), interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(mock, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = gray.shape
    up = lambda q: np.float32(q) * S + (S - 1) / 2

    def warp(name_png, quad):
        img = cv2.imread(str(pages / f"{name_png}.png"), cv2.IMREAD_COLOR)
        ih, iw = img.shape[:2]
        sc = np.linalg.norm(quad[1] - quad[0]) * 1.25 / (iw - 2 * BLEED)
        small = cv2.resize(img, (round(iw * sc), round(ih * sc)), interpolation=cv2.INTER_AREA)
        b, tw, th = BLEED * sc, (iw - 2 * BLEED) * sc, (ih - 2 * BLEED) * sc
        M = cv2.getPerspectiveTransform(np.float32([[b, b], [b + tw, b], [b + tw, b + th], [b, b + th]]), quad)
        return cv2.warpPerspective(small, M, (W, H), flags=cv2.INTER_CUBIC,
                                   borderMode=cv2.BORDER_REPLICATE).astype(np.float32)

    def mask(poly):
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [np.round(poly).astype(np.int32)], 255)
        return cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), 0.7)

    curve = [(x, y) for x, y in zip(xs, ys)]
    curve = [(float(front_q[3][0]), curve[0][1])] + curve   # nối đường cong ra tới mép trái trang
    tq, fq, bq = up(top_q), up(front_q), up(back_q)
    front_poly = up([front_q[0], front_q[1], *[(x, y) for x, y in reversed(curve)], front_q[3]])
    below = up([*curve, (front_q[1][0], back_q[2][1] + 2), (back_q[3][0], back_q[3][1] + 2)])
    m_top, m_front = mask(tq), mask(front_poly)
    m_back = np.clip(mask(bq) * mask(below) * (1 - m_front), 0, 1)
    b, gch, r = [mock[..., i].astype(np.float32) for i in range(3)]
    hand = np.clip((r - b - 45) / 10, 0, 1)                   # da tay (đỏ hơn xanh rõ) -> giữ mockup
    local = cv2.medianBlur(np.clip(gray, 0, 255).astype(np.uint8), 41).astype(np.float32)
    dark = np.clip((local - cv2.GaussianBlur(gray, (0, 0), 0.8) - 28) / 14, 0, 1)   # lò xo, đinh, lỗ
    # nhân theo TỪNG kênh màu: bóng dưới trang cong trên mockup ánh ấm -> tranh trong bóng cũng ấm như thật
    mf = mock.astype(np.float32)
    m_sharp = np.clip(mf * 1.6 - cv2.GaussianBlur(mf, (0, 0), 1.2) * 0.6, 0, 255)
    paper_rgb = np.float32([np.percentile(mf[..., i][m_top > 0.9], 95) for i in range(3)])
    shade = np.clip(m_sharp / paper_rgb, 0, 1.0)
    out = mock.astype(np.float32)
    m = cfg["month"]
    for layer_name, quad, msk in ((f"m{m:02d}_month", tq, m_top), (f"m{m:02d}_grid", fq, m_front),
                                  (f"m{m + 1:02d}_grid", bq, m_back)):
        layer = warp(layer_name, quad)
        layer = np.clip(layer * 1.45 - cv2.GaussianBlur(layer, (0, 0), 1.0) * 0.45, 0, 255)
        a = (msk * (1 - hand) * (1 - dark))[..., None]
        out = out * (1 - a) + layer * shade * a
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _save(out_path, out)


def _save(out_path: Path, img) -> None:
    """Ảnh listing lưu JPG q92 (nhẹ ~8 lần PNG, Etsy vẫn nét); ảnh debug/PNG giữ nguyên."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = np.clip(img, 0, 255).astype(np.uint8)
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        cv2.imwrite(str(out_path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    else:
        cv2.imwrite(str(out_path), img)


# 5 ảnh preview cho listing, theo thứ tự hiển thị: bìa, tờ mở, 3 tờ trên bàn, treo tường, để bàn
PREVIEWS = ["front_cover_spiral", "open_spread_flat", "three_open_spreads", "wall_spread", "wall_page_turn"]
# "AI gen mockup": 04 = 2 tờ treo tường (thay ảnh treo tường mở đôi), 05 lật trang bị bỏ, 06 = 3 cuốn -> vẫn 5 ảnh
AI_MOCKUP_PREVIEWS = ["front_cover_spiral", "open_spread_flat", "three_open_spreads", "two_wall_spreads",
                      "wall_page_turn", "three_books"]
# lịch grid in sẵn: bìa (dùng lại), treo tường thẳng, treo tường chéo, 3 tờ trên bàn, 2 cuốn gập
PREMADE_PREVIEWS = ["front_cover_spiral", "premade_wall_straight", "premade_wall_angled", "premade_three_spreads",
                    "premade_two_closed"]


def sheet_pages(sheet: dict) -> list[str]:
    """Tên các trang render/printify/*.png mà một tờ trong mockup dùng tới."""
    if sheet.get("source"):
        return [sheet["source"]]
    m = sheet["month"]
    if sheet["kind"] == "spread":
        return [f"m{m:02d}_month", f"m{m:02d}_grid"]
    if sheet["kind"] == "curl":
        return [f"m{m:02d}_month", f"m{m:02d}_grid", f"m{m + 1:02d}_grid"]
    return [f"m{m:02d}_month"]


def _dependencies(name: str, pages: Path) -> list[Path]:
    """Mọi đầu vào có thể làm preview thay đổi, dùng cho cache chính xác."""
    cfg = MOCKUPS[name]
    deps = [Path(__file__), HERE / cfg["file"]]
    for sheet in cfg["sheets"]:
        deps.extend(pages / f"{n}.png" for n in sheet_pages(sheet))
    return deps


def previews(concept_dir: Path, on_event=print) -> list[Path]:
    """Tạo 5 ảnh preview từ 11x8.5/ -> preview/NN_<mockup>.jpg. Ảnh nào còn mới thì bỏ qua."""
    from .. import layout

    import json
    from .. import products

    pages = layout.print_dir(concept_dir)
    out_dir = layout.listing(concept_dir)
    try:
        concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        concept = {}                                   # không đọc được concept: coi là lịch thường
    made, errors = [], []
    for i, name in enumerate(preview_names(concept), 1):
        out = out_dir / f"{i:02d}_{name}.jpg"
        if name in skipped_previews(concept):
            out.unlink(missing_ok=True)         # chế độ AI mockup bỏ ảnh lật trang
            continue
        if name == "two_wall_spreads":          # cuốn làm trước 02/10: ảnh treo tường cũ ở cùng số thứ tự
            (out_dir / f"{i:02d}_wall_spread.jpg").unlink(missing_ok=True)
        try:                                    # một tấm lỗi không chặn các tấm còn lại
            deps = _dependencies(name, pages)
            missing = [p.name for p in deps if not p.is_file()]
            if missing:
                raise FileNotFoundError(f"thiếu trang {', '.join(missing)}")
            newest = max(p.stat().st_mtime for p in deps)
            if out.exists() and out.stat().st_mtime >= newest:
                continue
            render(name, pages, out)
            on_event(f"  preview {out.name}")
            made.append(out)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{out.name}: {e}")
            on_event(f"  ⚠ Không ghép được {out.name}: {e}")
    if errors:
        raise PreviewError(made, errors)
    return made


class PreviewError(RuntimeError):
    """Có tấm preview không ghép được; `made` = các tấm vẫn ghép xong."""

    def __init__(self, made: list[Path], errors: list[str]):
        super().__init__("; ".join(errors))
        self.made, self.errors = made, errors


def preview_names(concept: dict) -> list[str]:
    from .. import products
    if products.ai_mockups(concept):
        return AI_MOCKUP_PREVIEWS
    return PREVIEWS if products.ai_grid(concept) else PREMADE_PREVIEWS


def skipped_previews(concept: dict) -> set[str]:
    """Preview không làm cho cuốn này (giữ số thứ tự các ảnh còn lại): AI mockup bỏ ảnh lật trang."""
    from .. import products
    return {"wall_page_turn"} if products.ai_mockups(concept) else set()


def missing_previews(concept_dir: Path) -> list[str]:
    """Tên file preview còn thiếu của cuốn (loại lịch không có mockup thì rỗng)."""
    import json
    from .. import layout, products
    try:
        concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        concept = {}
    if not products.get(concept)["mockups"]:
        return []
    out_dir = layout.listing(concept_dir)
    skip = skipped_previews(concept)
    return [f"{i:02d}_{n}.jpg" for i, n in enumerate(preview_names(concept), 1)
            if n not in skip and not (out_dir / f"{i:02d}_{n}.jpg").is_file()]


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--list":
        print("\n".join(MOCKUPS))
    elif len(sys.argv) == 4:
        render(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), debug=True)
    else:
        print(__doc__)
        sys.exit(1)
