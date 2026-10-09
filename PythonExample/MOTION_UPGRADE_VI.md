# Nâng cấp chuyển động nhanh và mượt

Đã chạy thử bàn tay thật trên COM3. Người dùng quan sát và xác nhận: **Nhanh và mượt hơn**.

| Thao tác | Bản trước: linear, 20°/giây | Bản mới: smooth, 40°/giây | Giảm thời gian |
| --- | ---: | ---: | ---: |
| open_all | 19.89 s | 10.50 s | 47.2% |
| close_all | 19.38 s | 10.56 s | 45.5% |

Cả hai bản được đo co/duỗi với cùng các góc đích đã hiệu chỉnh. Thời gian bao gồm chờ ổn định, 2 giây giám sát giữ tư thế và đọc lại trạng thái.

## Thay đổi

- Quỹ đạo bậc năm giúp khởi động và dừng êm, với vận tốc và gia tốc yêu cầu bằng 0 ở đầu/cuối. Thời gian quỹ đạo được tính theo tốc độ đỉnh, tối đa 40°/giây.
- Đọc gộp vị trí, tải, điện áp, nhiệt độ và trạng thái trong một gói cho mỗi servo; giữ cả lỗi trong gói trả lời và thanh ghi trạng thái. Từ 40 lượt đọc xuống 8 lượt đọc cho mỗi bộ phản hồi.
- Nhịp phản hồi thực đo: khoảng 8.2 → 37.7 lần/giây. Nhịp chờ gửi mục tiêu mới là 20 ms; thời gian giao tiếp được cộng vào chu kỳ thực tế.
- Mục tiêu theo sát vị trí đo trong khoảng dẫn tối đa 6°; độc lập với ngưỡng dừng 8°. Nếu servo chậm, pha quỹ đạo chờ để bắt kịp rồi tiếp tục. Bộ đếm kẹt, tải, nhiệt độ và điện áp vẫn hoạt động.
- Mức duỗi `(67,58,37,35)`, mức co `(92,90,90,90)` và sai số xác nhận cuối hành trình 4° được giữ.

## Kết quả chạy thật

| Thao tác | Kết quả | Thời gian |
| --- | --- | ---: |
| open_all | PASS | 10.50 s |
| close_all | PASS | 10.56 s |
| v_sign | PASS | 11.22 s |
| raise_index | PASS | 10.75 s |
| raise_middle | PASS | 10.62 s |
| raise_ring | PASS | 10.04 s |
| raise_thumb | PASS | 9.07 s |
| final_open | PASS | 10.48 s |

Trong log chạy mới: sai lệch chuyển động lớn nhất 5.99°, tải tuyệt đối lớn nhất 255 (đơn vị thô), nhiệt độ cao nhất 36°C, điện áp thấp nhất 4.4 V. Các cờ trạng thái ghi nhận: [0, 1].

Các lượt chạy dùng `ALLOW_VOLTAGE_WARNING=True` đã có: cho phép riêng cờ điện áp trong dải 4–7,4 V. Mọi cờ khác và các kiểm tra tải/nhiệt độ/vị trí vẫn được giữ. Không ghi EEPROM/PID.

50 kiểm thử phần mềm đã qua, gồm tính đơn điệu và tốc độ đỉnh quỹ đạo, tiếp tục pha sau khi chờ, giải mã khối phản hồi, lỗi gói trả lời, dữ liệu hỏng, servo chậm/kẹt, sai lệch vượt 8°, điện áp/tải và toàn bộ 13 cell notebook với servo giả.

## Sử dụng

Mở lại `AmazingHand_Control.ipynb`, chọn **AmazingHand (.venv)** và chạy lại cell khởi tạo. Cấu hình mới:

```python
SPEED_DEG_S = 40
MOTION_PROFILE = "smooth"
```

Để so sánh với chế độ trước, chọn `SPEED_DEG_S = 20`, `MOTION_PROFILE = "linear"` rồi chạy lại cell khởi tạo. Bốn cell thử hiệu chỉnh riêng vẫn chạy 4°/giây.

Bàn tay được để giữ tư thế duỗi sau thử nghiệm. JSON chi tiết: `MOTION_UPGRADE_VI.json`.
