# Kiểm tra notebook trên bàn tay thật

Bắt đầu (UTC): 2026-10-09T08:21:40Z. COM3, 1.000.000 baud, kernel `.venv` của project.

Đã chạy chính mã nguồn của từng cell trong `AmazingHand_Control.ipynb`, lần lượt một lần trên phần cứng thật. Mỗi thao tác được đọc lại phản hồi; các kết quả và output được lưu trong notebook. Bốn cell thử chậm chỉ gửi lệnh tới đúng cặp servo của ngón được chọn.

| Cell code | Chức năng | Kết quả | Thời gian (s) | Sai số servo lớn nhất (°) |
| --- | --- | --- | ---: | ---: |
| 1 | Khởi tạo và đọc 8 servo | PASS | 0.17 | 0.00 |
| 2 | Duỗi cả 4 ngón | PASS | 16.8 | 1.76 |
| 3 | Co cả 4 ngón | PASS | 20.28 | 3.22 |
| 4 | Dấu V / hi sign | PASS | 20.66 | 1.46 |
| 5 | Giơ riêng index | PASS | 21.48 | 3.22 |
| 6 | Giơ riêng middle | PASS | 19.3 | 2.64 |
| 7 | Giơ riêng ring | PASS | 18.7 | 3.22 |
| 8 | Giơ riêng thumb | PASS | 15.83 | 3.22 |
| 9 | Duỗi riêng index, 4°/giây | PASS | 42.74 | 0.88 |
| 10 | Co riêng index, 4°/giây | PASS | 43.03 | 2.34 |
| 11 | Duỗi riêng middle, 4°/giây | PASS | 39.56 | 1.46 |
| 12 | Co riêng middle, 4°/giây | PASS | 39.66 | 3.52 |
| 13 | Nhả torque cả 8 servo | PASS | 0.09 | 0.00 |
| final_open | Duỗi toàn bộ sau kiểm tra | PASS | — | 1.76 |

Sai số trong bảng so với thanh ghi mục tiêu servo đọc lại; góc yêu cầu được lượng tử hóa khi ghi xuống servo. Góc servo cần đối chiếu với hình dáng đốt ngón bằng quan sát.

## Những trường hợp lỗi đã kiểm tra

- **`close_all()` / `raise_finger("middle")`:** các output cũ báo sai số 3,26° ở ID 3 và 3,01° ở ID 1. Đã tái hiện `close_all()`; sau khi chờ, ID 3 dao động 2,97–3,26°, status=0, tải thô −195 đến −180. Notebook dùng `END_TOLERANCE_DEG = 4`, chờ tối đa 3 giây và cần 3 mẫu liên tiếp đạt ngưỡng trước khi xác nhận. Tư thế tiếp tục được giám sát trong 2 giây giữ. Mục tiêu góc co được giữ nguyên.
- **Sai lệch khi chạy nhanh:** quỹ đạo dựa vào vị trí đo và chờ servo bắt kịp. Giới hạn sai lệch chuyển động 8°, kiểm tra tải/nhiệt/điện áp, dừng khi kẹt và nhả torque khi lỗi vẫn hoạt động.
- **Cell giơ thumb báo ID 3 đứng yên 2 giây:** đã tái hiện ở vị trí 81,15°, mục tiêu cuối 85° (còn 3,85°, trong ngưỡng 4°), trong khi các ngón khác đang chạy. Đã sửa bộ đếm kẹt để chỉ tính khi servo còn ngoài vùng mục tiêu cuối; trường hợp đứng yên ngoài vùng đó vẫn dừng và nhả torque. Đồng thời sửa trường hợp index có hành trình ngắn khi chuyển từ V sang giơ riêng index: mục tiêu trung gian chỉ cách 2,56°, trong vùng dung sai servo, nhưng bộ đếm cũ vẫn báo kẹt. Bộ đếm mới yêu cầu 2 giây liên tục có mục tiêu hiện tại nằm ngoài dung sai và không có tiến triển. Có kiểm thử hồi quy cho cả hai tình huống và kiểm tra kẹt thật ở ngưỡng 3°/4°.
- **`unexpected keyword argument close_flexions`:** cell khởi tạo nạp lại các module theo thứ tự phụ thuộc, lấy class mới từ đúng thư mục project. Kiểm thử notebook bao gồm trường hợp kernel còn giữ class cũ.
- **`Parsing error`:** đọc trạng thái khởi tạo thử lại tối đa 3 lần đối với đúng lỗi parse, sau đó báo rõ ID. Lệnh chuyển động không được tự chạy lại khi lỗi.
- **Kernel thiếu `rustypot`:** cell khởi tạo hiện đã chạy thành công với interpreter `.venv` của AmazingHand. Notebook có thông tin kernel và hướng dẫn chọn interpreter đúng khi mở từ kernel khác.

## Cấu hình hiện tại

- `OPEN_EXTENSIONS = (67, 58, 37, 35)` theo thứ tự index, middle, ring, thumb. Index tăng riêng từ 62° lên 67°, đã thử qua các bước 62 → 64 → 66 → 67. Middle giữ 58°.
- `CLOSE_FLEXIONS = (92, 90, 90, 90)`; tốc độ yêu cầu 20°/giây cho 7 tư thế, 4°/giây cho 4 cell thử riêng.
- `END_TOLERANCE_DEG = 4`; có thể chọn 3/4/5 trong helper. Ngưỡng cuối hành trình và ngưỡng theo dõi chuyển động là hai kiểm tra riêng.
- Các lần chạy dùng `ALLOW_VOLTAGE_WARNING=True` như cấu hình trước. Khi thử duỗi riêng index, có mẫu ID 2 báo 4,4 V và status=1 (riêng cờ điện áp). Mẫu này được chấp nhận trong chế độ đã chọn với dải 4–7,4 V; các cờ lỗi khác, tải và nhiệt độ vẫn được giám sát. Log giữ nguyên số đo và cờ này.
- 42 kiểm thử phần mềm đã đạt, gồm kẹt thật, sai lệch 9°, lỗi tải/điện áp, ngắt thao tác, chờ ổn định, đóng cổng sau lỗi và chạy toàn bộ 13 cell với servo giả.

## Chạy lại

Mở lại notebook trên ổ đĩa, chọn **AmazingHand (.venv)**, chạy lại cell **Khởi tạo**, sau đó chọn cell tư thế cần dùng. Cell khởi tạo sẽ nạp helper mới và cấu hình 67°/58°/37°/35°. Nếu editor đang giữ bản notebook cũ trong RAM, dùng **Revert File** hoặc đóng mà không lưu rồi mở lại bản trên ổ đĩa.

Log chi tiết gốc: `.tools\hardware\notebook-review-1791534100294492400.json`. Bản JSON sao chép: `NOTEBOOK_CHECK_VI.json`.
