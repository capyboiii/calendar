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
├─ 2. Gen ảnh     ảnh neo trước -> bìa AI có typography + 12 tháng + họa tiết song song,
│                  mỗi job 1 chat, đính ảnh neo
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
python -m calforge render  <concept> [--months 1,3] [--placeholder-art x.png]
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
    jobs.json                  kế hoạch gen ảnh (anchor, cover AI, m01..m12, grid)
    art/raw/                   ảnh ChatGPT gen (<job>.png)
    art/final/                 ảnh đã upscale
    art/qc.md                  kích thước + độ lệch màu so với ảnh neo
    render/printify/           26 PNG upload Printify
    render/proof/              tùy chọn; mặc định không tạo để render nhanh
    render/digital/            calendar_11x8_5.pdf (printable 11×8.5")
    render/report.md           preflight, font, ảnh
    listing.json               title / mô tả / tag
    printify.json              id ảnh đã upload + product_id (sổ tiến độ Printify)
    status.json                đang ở bước nào, lỗi gì
```

Fast path: Real-ESRGAN chỉ chạy cho cover + 12 artwork được in, không upscale anchor/grid.
Render và listing được bỏ qua nếu artifact còn mới hơn concept/ảnh nguồn; preflight hình học
vẫn luôn chạy khi cần render. Printify upload tối đa 4 trang song song và tiếp tục từ
`printify.json` khi chạy lại.

Muốn làm lại một bước: xoá file kết quả của bước đó (vd xoá `art/raw/m05.png` để gen lại tháng 5).

## Style và màu

- **Art direction do AI đề xuất**: P1 nghĩ chủ thể, palette, bố cục và bề mặt từ chính
  chủ đề, người mua và cách cuốn lịch được sử dụng, sau đó thể hiện bằng đúng một trong ba medium sản xuất
  đã duyệt: Styled photography, Layered papercut hoặc Mid-century poster. P1 được xem dấu vân
  tay thị giác của các cuốn gần đây (medium, surface, composition) để tránh đổi tên nhưng lặp lại cùng
  một gu. Auto-pick giữ các phương án AI-feasibility 4-5 trong nhóm chất lượng cao rồi ưu tiên họ style
  ít dùng hơn. Vẫn có thể lọc thủ công theo nhãn bằng
  `python -m calforge ideate "keyword" --family styled_photography`.
- **Bố cục artwork theo từng cuốn**: P2 tạo `artwork_composition_system` riêng từ buyer và chủ đề;
  có thể là lệch tâm, toàn cảnh, flat-lay, close crop, chuyển động chéo, pattern hoặc một hệ khác phù
  hợp. Code chỉ giữ vùng an toàn in 80%, không còn ép mọi chủ thể vào giữa hay bắt phần trên/dưới cùng
  một kiểu. Ảnh tham chiếu khóa medium, palette và mark-making nhưng không được sao chép viewpoint hay
  cách đặt vật thể của ảnh neo.
- **Color story**: P2 chọn 3-4 màu có tên riêng cho niche, style bible phải dùng chúng; cấm nền kem
  mặc định (trừ niche vintage/giấy da).
- **Màu trang in** (`render/palette.py`): ý đồ màu của concept + sắc độ thật lấy từ ảnh neo; chữ tự
  đậm lên cho đủ tương phản. Ghi vào `palette.json` và `render/report.md`.
- **Grid do AI thiết kế theo art direction của cuốn (mặc định)**: tool sinh một ảnh `grid` làm
  nền giấy chung cho cả 12 tháng, bám ảnh neo của collection. Khi render, cùng một bố cục và họa tiết
  được giữ xuyên suốt; code chỉ thay tên tháng, câu trích, ngày và ngày lễ. Mép họa tiết được hòa dần vào màu giấy;
  chữ và lịch in trực tiếp lên một mặt giấy liên tục, không có card hay khung phủ lên. AI
  **không** vẽ ô, thứ, ngày hoặc chữ vì các phần này cần chính xác tuyệt đối. Khi render,
  AI chọn một trong năm bố cục an toàn cho từng cuốn (trái/phải, hai góc, top-center hoặc góc dưới),
  rồi cả 12 tháng của cuốn dùng nhất quán lựa chọn đó. Ảnh nền có quá nhiều chi tiết hoặc mảng tối trong
  vùng đặt lịch sẽ bị từ chối và sinh lại.
  `render/pages.py` vẽ vector 7 cột và số hàng thật (4/5/6) từ lịch Gregory, đặt toàn bộ chữ/ngày
  bằng code. Lịch mặc định 2027 lưu đủ 365 ngày trong `core/calendar_2027.py`; preflight đối chiếu
  độc lập từng ngày với `datetime`, bắt thiếu/trùng/sai ô và chữ lễ tràn. `render/calendar_audit.json`
  lưu kết quả theo tháng. Chạy `python -m tools.verify_calendar_render <concept-dir>` để kiểm tra
  tiếp vị trí số ngày trong PDF đã xuất. Nền thiếu thì preflight báo thiếu, không coi cuốn là hoàn tất. Sáu layout đã duyệt
  (`02`, `04`, `14`, `18`, `22`, `24`) vẫn chọn thủ công bằng `--grid-preset <tên>`; chế độ này
  không cần 12 trang AI. Studio hiển thị preview của grid AI-designed và một layout thủ công.
  CSV của `chatgpt-automation` không đính ảnh tham chiếu được, nên CSV chỉ xuất 14 artwork cơ bản;
  ảnh `grid` được sinh sau đó bằng driver có đính ảnh neo.

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
