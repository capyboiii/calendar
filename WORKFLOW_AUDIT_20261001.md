# Kiểm tra workflow — 01/10/2026

## Kết quả

- Bộ test hiện có: **198/198 PASS**, chạy toàn bộ bằng `python -m unittest discover -s tests -t . -v`, 252,502 giây.
- Kiểm thử bổ sung các bước nối workflow: **1 PASS, 5 FAIL** (6 test riêng trong `tests/test_workflow_audit.py`). Bộ test toàn bộ bắt đầu trước khi thêm file này.
- Tổng cộng 204 test đã chạy: 199 PASS, 5 FAIL.
- `node --check calforge/ui/static/app.js`: PASS.
- Chỉ bổ sung test và báo cáo trong đợt này; chưa sửa logic ứng dụng.

## Các lỗi đã tái hiện

| Mức độ | Tình huống | Kết quả thực tế | Ảnh hưởng |
|---|---|---|---|
| P1 | Batch ghi quá 3.000 dòng log, UI đã nhận đủ 3.000 dòng | Server cắt log đầu nhưng UI tiếp tục hỏi `since=3000`; server trả mảng rỗng | Log và tiến độ tính từ log ngừng cập nhật dù batch còn chạy |
| P1 | Cuốn đã có state R2, lượt upload tiếp theo thất bại | Calendaria vẫn đưa cuốn vào CSV và ghi `calendaria_exported_at` | Có thể xuất dữ liệu cũ/chưa đủ và bỏ sót khi chọn cuốn chưa xuất |
| P1 | Trang in đã có nhưng PDF Printable thiếu | CSV vẫn tạo hai biến thể Printable có `Variant File` rỗng | Import có thể tạo sản phẩm số không có file tải |
| P2 | Vẽ lại một trang của cuốn đã xuất Calendaria | `calendaria_exported_at` không bị xóa | Chọn cuốn chưa xuất không tự chọn cuốn vừa sửa; chọn thủ công vẫn xuất lại được |
| P2 | Đổi bucket và public URL, giữ nguyên file cục bộ | 0 file được upload sang bucket mới; state giữ URL cũ | Chuyển kho lưu trữ không có hiệu lực như người dùng mong đợi |

Test tái hiện: `python -m unittest tests.test_workflow_audit -v`.

Vị trí nguyên nhân:

- Log: `calforge/ui/server.py`, `Task.append_log` và `Task.to_dict`; frontend `pollTask` trong `calforge/ui/static/app.js`.
- Upload lỗi: `calforge/publish/calendaria_csv.py`, `publish_all`, danh sách `todo` không loại cuốn upload lỗi.
- PDF thiếu: `calforge/publish/calendaria_csv.py`, `_book_rows`, không kiểm tra URL PDF trước khi tạo Printable.
- Vẽ lại: `calforge/pipeline.py`, `redo_pages`, chỉ xóa trạng thái xuất Printify cũ.
- Đổi bucket: `calforge/publish/r2.py`, `push_book`, chỉ so sánh size/mtime, không đối chiếu đích upload.

## Phạm vi đã kiểm tra

- Tạo ý tưởng P1/P1b/P2, sửa JSON, mất ngữ cảnh, bộ nhớ đệm, phân bổ style/tông màu.
- Batch nhiều chủ đề; 18 cuốn/lượt mô phỏng, 15 tài khoản, ba seed lỗi ngẫu nhiên; hai loại lịch và hai chế độ grid. Mô phỏng có thể gọi làm nốt thêm tối đa ba lần, không chứng minh mọi cuốn đều xong ở lượt đầu.
- Điều phối chat/vẽ, giới hạn Chrome, hết quota, lỗi điều hướng, nhường tài khoản cho chat.
- Tạm dừng/tiếp tục, làm nốt, phục hồi sau dừng giữa batch và mở lại hàng đợi, gộp yêu cầu trùng.
- Vẽ lại trang, hoàn thiện sách, tái tạo mockup AI; cache ảnh/render/listing.
- Ngày tháng 2027, ngày lễ, bố cục grid, nền chung, grid in sẵn, trang AI và OCR với fixture.
- Render và PDF thực trong test cục bộ, kiểm tra khổ 11 x 8.5 và 14 x 11.5 inch.
- Mockup: nguồn ảnh, cache và orchestration; không thẩm định thẩm mỹ mọi sản phẩm.
- R2 giả lập, CSV Printify/Calendaria, chọn lại cuốn, số thuộc tính variant, Paper/N/A.
- API giao diện qua HTTP cục bộ, phục vụ file, chặn đường dẫn vượt thư mục, vòng đời tài khoản trong test.

## Giới hạn của kết quả

Không chạy một đợt tạo lịch mới bằng 15 tài khoản ChatGPT thật; không upload/publish lên R2, Printify hoặc website thật. Chrome/ChatGPT và dịch vụ xuất bản dùng mock trong mô phỏng. Upscale được kiểm tra luồng xử lý/cache, chưa benchmark Real-ESRGAN trên GPU thật. API giao diện được test, chưa bấm toàn bộ giao diện trong trình duyệt. Vì vậy PASS không bảo đảm các dịch vụ thật, phiên đăng nhập hoặc import storefront đều hoạt động.

Có ResourceWarning về file font và file CSV test chưa đóng; bộ test vẫn hoàn tất thành công. Chưa đủ bằng chứng coi đây là rò tài nguyên gây lỗi batch thực tế.

Ưu tiên xử lý log dài và không đánh dấu thành công khi xuất bản thiếu/lỗi, sau đó đồng bộ trạng thái vẽ lại và đích R2. Các lỗi này không phụ thuộc RAM/GPU.
