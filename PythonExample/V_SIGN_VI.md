# Dấu V / peace trên bàn tay thật

Chạy từ thư mục gốc project, sau khi cắm nguồn và USB:

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_VSign.py --port COM3 --allow-voltage-warning
```

Script chạy **một lần**, đồng thời điều khiển cả tám servo ở 4°/giây, rồi giữ tư thế bằng torque: index và middle giơ/tách ra; ring và thumb co xuống. Giữ tay và đồ vật ngoài cơ cấu khi chạy. Từ tư thế mở hiện tại, thời gian khoảng 35 giây.

Mặc định dùng bàn tay phải theo `Side=1` trong demo gốc, mức duỗi index/middle 39° đang dùng trên bàn tay này, độ tách 15°. Cách tách lấy từ hàm `Victory()` trong `AmazingHand_Demo.py`; các offset đọc từ `MiddlePos` mà không import chương trình demo gốc. Mục tiêu ID 1–8 với offset hiện tại: `[-21, 54, -59, 16, 88, -85, 78, -90]°`.

Các tùy chọn:

- `--spread 0`: index/middle giơ song song. Độ tách được phép 0–25°.
- `--spread 25 --extension 40`: góc tương đối đúng với `Victory()` gốc. Mức duỗi được phép 35–40°; đây là góc servo, không phải góc đo tại khớp ngón.
- `--side left`: đảo hướng tách cho bàn tay trái.
- `--dry-run`: chỉ đọc và kiểm tra mục tiêu, không gửi lệnh chuyển động hoặc torque.

Tùy chọn `--allow-voltage-warning` dùng chế độ chẩn đoán đã thử trong phiên này: cho qua riêng cờ điện áp 0x01 khi điện áp servo báo còn trong 4–7,4 V. Các cờ khác, tải, nhiệt độ, giới hạn góc và sai lệch vị trí vẫn được kiểm tra. Mặc định không có tùy chọn này thì script giữ kiểm tra điện áp nghiêm ngặt. Không ghi EEPROM hoặc tự sửa offset.

Nhấn Ctrl+C khi script đang di chuyển sẽ cố nhả torque cả tám servo. Khi script đã hoàn tất và đang giữ tư thế, nhả torque bằng:

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_HardwareDemo.py --port COM3 --release
```

Logic đã được kiểm tra với servo giả: góc hai bên đúng `Victory()` gốc, giữ đúng tư thế không chạy chu kỳ, dry-run không ghi lệnh, lỗi tải nhả toàn bộ và mục tiêu ngoài giới hạn không chuyển động. Vị trí servo đạt mục tiêu vẫn cần đối chiếu bằng quan sát hình dáng ngón thật.

Đã chạy thật với cấu hình mặc định và `--allow-voltage-warning`: cả tám servo tới mục tiêu, sai lệch lớn nhất 1,29°, giữ tư thế trong hai giây kiểm tra rồi để torque bật. Đã kiểm tra tổng cộng 19 bài test giả cho các lệnh điều khiển hiện có và dấu V.
