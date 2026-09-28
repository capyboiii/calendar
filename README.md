# calendar (calforge)

Tool sản xuất hàng loạt lịch treo tường 11×8.5" và 14×11.5" (Printify, nhà in District Photo) kèm PDF in
tại nhà, để bán trên Etsy/Shopify cho người mua Mỹ. **Người dùng chỉ đưa chủ đề và số cuốn.** ChatGPT nghĩ
ý tưởng và vẽ tranh; code lo mọi thứ phải ĐÚNG (ngày, ngày lễ, lời Kinh Thánh, bố cục in, kiểm tra).

Hướng dẫn cho người dùng (không cần biết kỹ thuật): **[HUONG_DAN.html](HUONG_DAN.html)** (mở bằng trình duyệt, hoặc nút *Hướng dẫn* trên UI).

## Chạy nhanh

Máy mới: bấm đúp **`CAI_DAT.bat`** (tự cài Python/Chrome nếu thiếu, môi trường `.venv`, thư viện, torch khi có GPU
NVIDIA, font/KJV/mô hình, biểu tượng ngoài màn hình), sau đó mở bằng **`start_ui.bat`**. Đóng gói gửi người khác:
`python tools/package.py` -> `dist/CalForge_Studio_<ngày>.zip` (không kèm dữ liệu riêng).

Cài tay (dev):

```bash
pip install -r requirements.txt
python tools/fetch_assets.py          # font Google Fonts (OFL), KJV, trọng số Real-ESRGAN
python -m calforge ui                 # mở CalForge Studio trên trình duyệt
```

Trong Studio: thêm tài khoản ChatGPT (từng cái hoặc **Đăng nhập hàng loạt**), chọn **loại lịch**, nhập
**chủ đề** + **số cuốn**, bấm **Bắt đầu**. Có thể đóng trang, máy vẫn chạy; mở lại để xem tiến độ.

## Hai loại lịch (`calforge/products.py`)

| Loại | Máy làm | Trang in mỗi khổ | Preview |
|---|---|---|---|
| `wall_grid` (mặc định) | ý tưởng, tranh, **nền grid AI** + lịch ngày do code dựng | 26 | 5 mockup |
| `wall_premade` | ý tưởng, tranh; trang grid lấy mẫu có sẵn `formats/premade_wall_*/grids/` | 26 (14 nếu chưa có grid) | 5 mockup riêng |

Trang grid in sẵn năm khác: `python tools/make_premade_grids.py 2028`.

## Dây chuyền

```
chủ đề + N cuốn  (batch chia lượt tối đa 3 cuốn)
 ├─ 1. Ý tưởng   P1 nghĩ 3×n ý (chia đều 3 style) -> P1b duyệt trùng với cả danh mục (chat riêng)
 │               -> P2 concept 12 tháng (mỗi cuốn 1 chat) -> kiểm tra -> P3 sửa lỗi
 ├─ 2. Gen ảnh   ảnh neo -> bìa + 12 tranh song song trên mọi tài khoản (+ nền grid AI)
 │               upscale Real-ESRGAN chạy song song trong lúc chờ ChatGPT vẽ
 ├─ 3. Hậu kỳ    render 2 khổ + PDF in tại nhà, 5 ảnh preview, listing, Printify (nháp)
 │               -> chạy nền trong lúc cuốn sau gen ảnh
 └─ Cuối batch   vòng vét cuốn dở + "Báo cáo batch.md"
```

- **Chống trùng** do AI làm: P1/P1b đọc "dấu vân tay" của mọi cuốn đã làm (lời hứa, thế giới cảnh, 12 cảnh).
- **Chia đều**: style tranh (ảnh chụp / giấy cắt / poster) theo lượt; chất liệu nền grid (màu nước /
  thủ công / laid) và 5 bố cục trang lịch (`render/grid_layouts.py`) theo danh mục, tránh khoá cặp.
- **Cô lập lỗi**: một cuốn hỏng chỉ ghi lý do + traceback vào `status.json` của nó, batch đi tiếp.
- **Hết lượt ChatGPT**: nhận ra qua mã HTTP 429/503 và câu thông báo (`llm/limits.py`); cả 5 tài khoản
  hết lượt thì batch tạm dừng, thử lại mỗi `quota_wait_s` (mặc định 30 phút), tối đa `quota_max_wait_h`.
- **Chạy lại** cùng chủ đề khi batch dở: làm nốt đúng phần còn thiếu (`_he_thong/batch.json`).

## Cấu hình

Copy `calforge.example.json` thành `calforge.json` (đã gitignore). Mục chính:
- `profiles_dir`: thư mục Chrome profile (tài khoản ChatGPT) **riêng của calforge**, mặc định `.chrome-profiles/`
  trong repo (đã gitignore - chứa phiên đăng nhập). Không dùng chung với chatgpt-automation, nên hai tool chạy
  song song được. `chatgpt_automation_dir` chỉ cần cho lệnh `plan`/`import` (đường vòng CSV).
- `llm.profiles` / `imagegen.profiles`: `null` = mọi tài khoản, xoay vòng; hết lượt tự đổi.
- `llm.headless` / `imagegen.headless`: `"hidden"` = Chrome chạy ngầm ngoài màn hình (mặc định), `false` = hiện.
- `quota_wait_s`, `quota_max_wait_h`, `batch_retry_wait_s`: chờ khi hết lượt.
- `printify.token` (hoặc biến môi trường `PRINTIFY_API_TOKEN`), `printify.shop_id`, `printify.price_cents`.

**Tài khoản**: đăng nhập hàng loạt dán mỗi dòng `email | mật khẩu | mã 2FA`; mật khẩu chỉ nằm trong RAM,
không ghi đĩa/log. Email đã có tài khoản thì bỏ qua. Gặp captcha thì dừng để người dùng tự xác minh.

## Lệnh

```bash
python -m calforge run "keyword" --auto 6 [--product wall_premade] [--no-printify] [--publish]
python -m calforge produce <cuốn>                    # concept có sẵn -> sản phẩm
python -m calforge ideate "keyword" [--auto N] [--more] [--manual]
python -m calforge gen | upscale | render | listing | printify <cuốn>
python -m calforge ui [--port 8080]
python -m tools.verify_calendar_render <cuốn>        # đối chiếu ngày trong PDF đã xuất
```

## Thư mục

```
projects/
 Wall Calendar (Blank)/ | Wall Calendar/   loại lịch (máy tự vẽ grid | grid in sẵn)
 <chủ đề>/
  <Tên cuốn>/
    preview/        5 ảnh quảng cáo
    11x8.5/         trang PNG upload Printify + in_tai_nha_11x8.5.pdf
    14x11.5/        như trên
    _he_thong/      (ẩn) concept/listing/status.json, anh_ai/, anh_upscale/, ky_thuat/
  Báo cáo batch.md  cuốn nào xong, dừng ở bước nào, vì sao
  _he_thong/        (ẩn) angles.json, batch.json, ideation/ (sổ hỏi/đáp ChatGPT)
```

Đường dẫn lấy từ `calforge/layout.py`. Muốn làm lại một bước: xoá file kết quả của bước đó
(vd `_he_thong/anh_ai/m05.png` để gen lại tháng 5) rồi chạy lại.

## Kiểm tra tự động

- **Concept** (`ideation/validate.py`): schema, ngày lễ đúng tháng theo lịch thật, mã câu KJV có thật,
  font OFL, tương phản chữ ≥ 4.5:1, từ cấm (`data/banned_terms.txt`).
- **Ảnh** (`imagegen/generate.py`): tỉ lệ/kích thước, so màu với ảnh neo, nền grid đủ sạch ở vùng đặt lịch.
- **Trang in** (`render/preflight.py`): chữ trong lề, không chạm lò xo/lỗ treo/mã vạch, cỡ ≥ 6pt, không
  chồng chữ; đối chiếu độc lập từng ngày với `datetime` (thiếu/trùng/sai ô).

Số đo template: `formats/<khổ>/format.json`. Mockup preview: `render/mockups.py` + `data/mockups/`.

## Test

```bash
python -m unittest discover -s tests -t .
```
