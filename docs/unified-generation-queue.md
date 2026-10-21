# Hàng đợi chung idea và clone

Idea, clone, làm tiếp và gen lại dùng `projects/.hang_doi.json`.
Mỗi dòng là một batch idea, một nhóm clone từ một link (1–5 cuốn), hoặc một việc sửa cuốn.
Ưu tiên theo thứ tự hiển thị, nhưng không đợi batch trước kết thúc nếu còn tài khoản rảnh.
Bộ điều phối đọc số profile đang được mượn, yêu cầu đang chờ, trần Chrome và RAM để mở
mục tiếp theo bằng phần dư. Không chia cứng 12 tài khoản mỗi cuốn và không giữ acc cho việc chưa sẵn sàng.
Ví dụ 40 acc đủ RAM, mỗi cuốn có 12 việc sẵn sàng: có thể phân 12 + 12 + 12 + 4.
Ưu tiên hoàn tất cuốn đã nhận, không mở đồng loạt mọi cuốn. Ngân sách cuốn dùng chung
giữa các tiến trình idea, clone, làm tiếp và gen lại: tự động tối đa 2 cuốn với 6–24
Chrome, tối đa 4 cuốn với 40 Chrome (1 Chrome thì 1 cuốn). Có thể đặt `max_active_books`.
Chỉ nhận cuốn tiếp theo khi còn chỗ và tài khoản rảnh; giữ chỗ đến hết hậu kỳ.
Giới hạn này tính theo trần Chrome/RAM thực tế, không chỉ số acc đã đăng nhập.
Cuốn chưa nhận hiện “Đang chờ”; chỉ cuốn đã nhận mới hiện “Đang làm”.
Tiến trình chết được thu hồi chỗ, còn tài khoản đang gen được chờ bình thường.
Số mục hàng đợi chạy đồng thời cũng chịu giới hạn này và mở giãn nhịp.
Tạm dừng dừng mọi mục đang chạy, giữ thứ tự để Tiếp tục.

Trong một batch, cơ chế lập idea/artwork/grid/hậu kỳ song song vẫn hoạt động.
Tài khoản không bị chia cố định theo hai chức năng. Clone chỉ dùng tài khoản Plus/K12 hợp lệ;
pool chung vẫn kiểm soát profile, RAM và số Chrome.
Mỗi mục đang chạy có thứ tự ưu tiên truyền tới các tiến trình con. Yêu cầu sẵn sàng của
mục trước được cấp acc trước mục sau, bao gồm cả chat và vẽ. Acc của mục sau đang gen
được hoàn thành ảnh hiện tại, rồi nhả nếu mục trước cần. Không đóng Chrome giữa ảnh.
Trong cùng mục vẫn giữ cơ chế ưu tiên trang lịch và luân phiên chống đói việc.
Nhánh artwork clone đã nhường acc được xin lại trong khi các nhánh khác còn vẽ;
không phải đợi toàn bộ nhóm nhánh kết thúc mới tiếp tục phần thiếu. Nếu mọi nhánh
đều đang chờ, trả việc về bộ điều phối chung; không giữ Chrome hay quay vòng liên tục.
Hai batch idea cùng chủ đề/sản phẩm/dự án không chạy chồng để tránh ghi chung batch.json.
Các lệnh làm tiếp/gen lại cùng cuốn, nhóm clone có mã cuốn giao nhau và lệnh sửa
cuốn đang thuộc batch idea/clone cũng chờ nhau để tránh ghi chung file. Mục độc lập
phía sau vẫn được dùng phần acc rảnh; mục đang chờ quyền ghi giữ nguyên trong hàng.

Clone được thêm trực tiếp vào hàng đợi chung. Lệnh con nhận các `--item` cụ thể;
quét thêm cuốn chỉ diễn ra trong tập mã đã giao, không lấy cuốn mới của hàng phía sau.
API clone/start cũ chỉ xếp các nhóm chưa được xếp, không tự mở tiến trình riêng.
API retry cũng xếp về cuối hàng, không chen trước. Việc đã xếp không bị thêm trùng.

Lần đầu nâng cấp, các nhóm clone pending/running cũ được nối sau hàng idea đang lưu;
thứ tự cũ của idea giữ nguyên. Cờ `unified` bảo đảm việc bị bỏ khỏi hàng không tự xuất hiện
lại sau mỗi lần mở tool. Cuốn clone chưa được xếp hoặc bị lỗi vẫn có phần thao tác riêng.
Khởi động lại đưa dòng running về queued, giữ danh sách cuốn và dữ liệu đã tạo.

UI dùng một danh sách để đổi thứ tự, tạm dừng và xem lịch sử cả hai chức năng.
Các khung tiến độ idea và clone vẫn dùng trình hiển thị phù hợp cho từng loại.
R2/CSV và cửa sổ đăng nhập vẫn độc lập với hàng gen.

Thay đổi cần được nạp bởi lần khởi động backend tiếp theo; không thay tiến trình đang gen.
Chưa đóng gói vào EXE.
