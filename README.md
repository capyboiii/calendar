# calendar (calforge)

Tool sản xuất lịch treo tường 11×8.5" (Printify "Wall Calendars (Blank)", District Photo) + bản
printable PDF. **Người dùng chỉ đưa keyword.** ChatGPT nghĩ ý tưởng và vẽ ảnh; code lo mọi thứ phải
ĐÚNG (ngày, ngày lễ, lời Kinh Thánh, bố cục in, kiểm tra).

```bash
python -m calforge run "christian"          # keyword -> sản phẩm NHÁP trên Printify
```

## Nguyên tắc

1. **AI lo phần đẹp, code lo phần đúng.** Lưới ngày, ngày lễ, lời câu Kinh Thánh, kích thước in
   không bao giờ để ChatGPT tự viết.
2. **Mọi output của ChatGPT đều qua kiểm tra.** Concept sai thì tool gửi danh sách lỗi cho ChatGPT
   sửa (P3); ảnh sai tỉ lệ/kích thước thì gen lại; trang in phải qua preflight mới được xuất.
3. **Ổ đĩa là sổ tiến độ.** Mỗi câu hỏi/đáp, mỗi ảnh, mỗi lần upload là một file; chạy lại thì đi
   tiếp từ chỗ dừng, không hỏi lại, không tốn lượt.
4. **Không tự làm việc không đảo ngược được.** Printify chỉ tạo sản phẩm NHÁP; publish phải có `--publish`.

## Dây chuyền

```
keyword
 ├─ 1. Ý tưởng     P1 góc tiếp cận -> chọn góc -> P2 concept (+ dữ kiện lịch do code tính)
 │                  -> kiểm tra -> P3 sửa lỗi -> concept.json            [ChatGPT web, acc chữ]
 ├─ 2. Gen ảnh     ảnh neo trước -> 12 tháng + họa tiết song song, mỗi job 1 chat, đính ảnh neo
 │                  -> kiểm tra tỉ lệ/kích thước, so màu với ảnh neo      [ChatGPT web, mọi acc]
 ├─ 3. Upscale     Real-ESRGAN x4 (GPU) + trộn 30% Lanczos giữ vân giấy -> art/final/
 ├─ 4. Render      bìa trước, 12 × (trang ảnh + trang lưới), bìa sau = 26 PNG 3375×2625 @300DPI
 │                  + preflight + proof đè template + PDF printable 11×8.5"
 ├─ 5. Listing     title, mô tả HTML, 13 tag (từ concept)
 └─ 6. Printify    upload 26 trang -> tạo sản phẩm NHÁP (publish chỉ khi --publish)
```

## Cài đặt

```bash
pip install -r requirements.txt
python tools/fetch_assets.py      # font Google Fonts (OFL), KJV (31,102 câu), trọng số Real-ESRGAN
```

Copy `calforge.example.json` thành `calforge.json` để đổi cấu hình. Các mục chính:
- `llm.profiles`: danh sách tài khoản ChatGPT cho bước ý tưởng, **xoay vòng**: mỗi lần chạy bắt đầu
  từ tài khoản sau tài khoản dùng lần trước; hết lượt thì tự chuyển. Cố định 1 tài khoản: `llm.profile`.
- `imagegen.profiles`: danh sách tài khoản gen ảnh (mặc định: mọi profile trong
  `chatgpt-automation/.chrome-profiles`). Một profile chỉ mở được ở một nơi - đừng chạy song song
  với chatgpt-automation trên cùng tài khoản.
- `printify.token` (hoặc biến môi trường `PRINTIFY_API_TOKEN`), `printify.shop_id`, `printify.price_cents`.

## Lệnh

```bash
python -m calforge run "keyword" [--pick r1a2] [--no-printify] [--publish]   # trọn gói
python -m calforge produce <concept>                 # concept có sẵn -> sản phẩm

# từng bước
python -m calforge facts --year 2027                 # dữ kiện ngày lễ bơm vào prompt
python -m calforge ideate "keyword" [--pick ..] [--more] [--manual]
python -m calforge angles "keyword"                  # xem các góc đã sinh
python -m calforge check   <concept>                 # kiểm tra lại concept.json
python -m calforge gen     <concept> [--profiles acc2,acc3]
python -m calforge upscale <concept>
python -m calforge render  <concept> [--months 1,3] [--placeholder-art x.png] [--placeholder-ornament y.png]
python -m calforge listing <concept>
python -m calforge printify <concept> [--publish]
python -m calforge plan / import <concept>           # đường vòng qua trang /csv của chatgpt-automation
python -m calforge ui [--port 8080]                  # mở giao diện web CalForge Studio
```

`<concept>` là thư mục `projects/<keyword>/<angle-id>-<slug>/`.

## Thư mục project

```
projects/<keyword>/
  ideation/                    sổ hỏi/đáp ChatGPT: <label>.prompt.md / .response.md
  angles.json                  mọi góc tiếp cận đã sinh
  <angle-id>-<slug>/
    concept.json               concept đã qua kiểm tra (+ lời câu KJV)
    concept_report.md          cảnh báo cho người duyệt
    jobs.json                  kế hoạch gen ảnh (anchor, m01..m12, ornament)
    art/raw/                   ảnh ChatGPT gen (<job>.png)
    art/final/                 ảnh đã upscale
    art/qc.md                  kích thước + độ lệch màu so với ảnh neo
    render/printify/           26 PNG upload Printify
    render/proof/              đè template Printify để soát lò xo / lỗ treo / mã vạch
    render/digital/            calendar_11x8_5.pdf (printable 11×8.5")
    render/report.md           preflight, font, ảnh
    listing.json               title / mô tả / tag
    printify.json              id ảnh đã upload + product_id (sổ tiến độ Printify)
    status.json                đang ở bước nào, lỗi gì
```

Muốn làm lại một bước: xoá file kết quả của bước đó (vd xoá `art/raw/m05.png` để gen lại tháng 5).

## Style và màu

- **Họ style** (`data/style_families.json`): màu nước, sơn dầu, khắc gỗ cổ, linocut, phẳng hiện đại,
  poster retro, cắt giấy, dân gian, nét mực + điểm màu, kính màu, minh họa bảo tàng, chì màu, ảnh chụp.
  P1 phải trải 5 góc ra ít nhất 4 họ, tối đa 1 góc màu nước. Khi tự chọn góc, tool ưu tiên họ **ít
  làm nhất trong danh mục** (`projects/*/*/concept.json`), rồi mới tới điểm "AI vẽ được".
  Ép một họ: `python -m calforge ideate "keyword" --family linocut_print`.
- **Color story**: P2 chọn 3-4 màu có tên riêng cho niche, style bible phải dùng chúng; cấm nền kem
  mặc định (trừ niche vintage/giấy da).
- **Màu trang in** (`render/palette.py`): ý đồ màu của concept + sắc độ thật lấy từ ảnh neo; chữ tự
  đậm lên cho đủ tương phản. Ghi vào `palette.json` và `render/report.md`.

## Kiểm tra tự động

- **Concept** (`ideation/validate.py`): đúng schema, 12 tháng không trùng cảnh; `holiday_tie` đúng
  tháng theo lịch thật; mã câu KJV có thật; font trong danh sách OFL; tương phản chữ ≥ 4.5:1;
  không chứa từ cấm (`data/banned_terms.txt`); giới hạn độ dài.
- **Ảnh** (`imagegen/generate.py`): ngang 3:2, cạnh dài ≥ 1024; ảnh lỗi thì gen lại (tối đa 3 lần);
  so màu với ảnh neo để gắn cờ ảnh lệch style.
- **Trang in** (`render/preflight.py`): chữ trong lề, không chạm lò xo/lỗ treo/ô mã vạch, cỡ ≥ 6pt,
  chữ không chồng nhau (đo theo nét thật của font), họa tiết không đè chữ, không lấn ô lưới.

Số đo template: `formats/printify_wall_11x8_5/format.json`. Vị trí vùng in trên Printify: tool tự
khớp theo tên; không chắc thì dừng và ghi `printify_positions.json` để điền tay.

## Test

```bash
python -m unittest discover -s tests -t .
```

## Còn lại

- [x] Giao diện web CalForge Studio (quản lý project, chọn/duyệt ảnh, soát proof, listing, task console)
- [ ] Kiểm tra chữ lẫn trong ảnh (OCR)
- [ ] Kiểm chứng tên vùng in thật của Printify (cần token) và đặt 1 cuốn in mẫu
- [ ] Lưới cho `family_columns`, `moon_phases`, `tracker` (hiện dùng lưới chuẩn)
