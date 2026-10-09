# Hiệu chỉnh index sau khi tháo lắp tay đòn servo

Index đã từng duỗi được trước khi chốt rơi. Chốt thay đã được người dùng xác nhận đúng thông số; trong lúc sửa, tay đòn servo cũng đã được tháo rồi lắp lại. Cần đối chiếu lại góc gốc sau tháo lắp. Chưa xác nhận tay đòn lệch bao nhiêu, hoặc khớp có bị bó.

Đã xác nhận qua quan sát: ID 1–2 điều khiển index. Tăng mức duỗi từ 35° lên 40° chưa làm đốt cuối thẳng. Chưa có lý do sửa firmware, PID hoặc tăng lực servo.

## Chuẩn bị: tách tay đòn khỏi trục servo

1. Ngắt nguồn servo và USB. Chỉ thao tác khi không còn cấp điện.
2. Tháo hai tay đòn của index khỏi hai trục servo. Giữ nguyên chốt khớp và các thanh liên kết. Xem hình định vị trong [trang 22 của hướng dẫn](../docs/AmazingHand_Assembly.pdf), hoặc [ảnh trích trang 22](../.tools/hardware/assembly-reference/page-22.png) nếu đang dùng bản workspace đã chuẩn bị.
3. Kiểm tra cơ cấu ngón đã tách khỏi servo có gập/duỗi trơn trên toàn hành trình không, theo trang 15. Nếu khớp vẫn bị chặn, dừng hiệu chỉnh servo và kiểm tra vị trí lắp liên kết, trục và phần vỏ đang chạm. Không ép qua điểm cứng.

## Đặt lại mốc cơ khí

1. Khi hai tay đòn đã tách hẳn khỏi trục motor, cắm lại USB và nguồn. Rút tay, dụng cụ khỏi các trục servo.
2. Chạy từ thư mục project:

   ```powershell
   .\.venv\Scripts\python.exe .\PythonExample\AmazingHand_CenterIndex.py --port COM3 --horns-detached
   ```

   Chương trình chỉ điều khiển ID 1–2, đưa trục trần về 0° ở tốc độ 5°/giây và đọc phản hồi vị trí. Mất khoảng 8–12 giây nếu bắt đầu ở vị trí gần lần kiểm tra. Sau khi kết thúc hoặc bị ngắt, chương trình cố nhả torque index. Tham số `--horns-detached` xác nhận bạn đã hoàn thành bước tách tay đòn; không dùng khi tay đòn còn gắn trên trục motor.

3. Khi thấy `CENTERED`, ngắt nguồn và USB. Lắp lại hai tay đòn theo hình trang 22, không xoay trục servo trong lúc lắp. Nếu không thể lắp như hình, dừng và đối chiếu lại cơ cấu.
4. Sau khi lắp xong và rút dụng cụ khỏi ngón, cắm lại nguồn/USB. Gửi ảnh định vị tay đòn trước khi thử duỗi tiếp; chỉ việc nhìn ngoài giống trước chưa xác nhận được mốc 0°.

Đây là đặt lại mốc cơ khí, chưa hoàn thành hiệu chỉnh tinh. Theo trang 23, mỗi servo còn cần góc `MiddlePos` riêng; không tự dùng các giá trị mẫu `[3, 0]` làm kết quả hiệu chỉnh của bàn tay này. Có thể tinh chỉnh khi cơ cấu đã chuyển động trơn và ảnh định vị được xác nhận.

## Kiểm tra phần mềm mà không chuyển động

Đọc trạng thái ID 1–2, không thay torque hay mục tiêu vị trí:

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_CenterIndex.py --port COM3 --dry-run
```

Script mới đã kiểm tra cú pháp và bốn trường hợp bằng bộ điều khiển giả: chế độ chỉ đọc không gửi lệnh, chỉ ID 1–2 được điều khiển, nhả torque khi hoàn tất hoặc lỗi truyền thông, và thiếu lựa chọn chế độ không mở cổng serial. Chưa chạy chuyển động về 0° trên phần cứng vì chưa xác nhận tay đòn đã tách. Không sử dụng chương trình `AmazingHand_Hand_FingerMiddlePos.py` cũ trực tiếp: nó đặt cổng COM11, tốc độ cao và chạy lặp vô hạn.
