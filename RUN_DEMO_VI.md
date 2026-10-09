# Chạy demo AmazingHand trên Windows

## Notebook điều khiển bàn tay thật

Bản mới dùng quỹ đạo mượt và đọc gộp phản hồi: co/duỗi thực đo giảm khoảng 46% thời gian. Xem [kết quả nâng cấp chuyển động](PythonExample/MOTION_UPGRADE_VI.md).

Mở [AmazingHand_Control.ipynb](PythonExample/AmazingHand_Control.ipynb) trong VS Code và chọn kernel **AmazingHand (.venv)**, hoặc chạy JupyterLab từ thư mục project:

```powershell
.\.venv\Scripts\jupyter-lab.exe .\PythonExample\AmazingHand_Control.ipynb
```

Chạy cell **Khởi tạo** trước, sau đó chọn một trong bảy cell: duỗi cả bàn tay, co cả bàn tay, dấu V, hoặc giơ riêng index/middle/ring/thumb trong khi ba ngón còn lại co xuống. Chạy từng cell và chờ hoàn thành; **Run All** sẽ chạy liên tiếp mọi tư thế. Cell cuối nhả torque. Mỗi thao tác tự đóng cổng serial khi xong; sau thao tác thành công servo vẫn giữ tư thế.

Tốc độ notebook hiện đặt ở `SPEED_DEG_S = 40` (tốc độ đỉnh 40°/giây), dùng `MOTION_PROFILE="smooth"` để tăng/giảm tốc êm. Tham số áp dụng đồng thời cho tốc độ servo và quỹ đạo của cả bảy tư thế. Có thể đổi giá trị trong cell khởi tạo rồi chạy lại; hoặc đặt `hand.speed_deg_s = 40` để áp dụng ngay cho đối tượng đang dùng. Các kiểm tra tải, nhiệt độ, điện áp, vị trí và xử lý ngắt vẫn hoạt động. Cell khởi tạo tự nạp lại các helper theo thứ tự phụ thuộc từ đúng project, tránh giữ class cũ gây lỗi `unexpected keyword argument 'close_flexions'`. Khi cập nhật notebook, mở lại file rồi chạy cell khởi tạo. CLI cũ vẫn mặc định 4°/giây.

Quỹ đạo nay tiến theo phản hồi servo, với tốc độ đặt là mức trần: nếu servo chậm hơn, chương trình chờ thay vì tiếp tục tăng mục tiêu theo thời gian. Giới hạn sai lệch khi đang chạy vẫn là 8°, xác nhận tư thế trong notebook là 4°, chờ tối đa 30 lượt kiểm tra cách nhau 0,1 giây và cần 3 mẫu liên tiếp đạt ngưỡng. Chế độ `smooth` dùng khoảng dẫn tối đa 6°; chế độ `linear` bắt đầu ở 4°. Nếu một servo chưa tiến triển trong 0,75 giây khi còn mục tiêu, cho phép một lần mở khoảng dẫn tới 6° để kiểm tra khả năng thắng ma sát/tải, vẫn giữ ngưỡng dừng độc lập 8°. Nếu mục tiêu hiện tại nằm ngoài dung sai và servo không tiến triển liên tục 2 giây thì nhả torque và dừng; không dò lặp. Có thời hạn cho toàn bộ chuyển động. Các lỗi serial, tải/nhiệt độ/điện áp vẫn dừng ngay.

Log lỗi co cho thấy ID 3 đứng ở 21,39° khi mục tiêu trung gian bị giữ ở 25,39°, tải thô 225, status=0. Sau khi thêm khoảng dẫn có giới hạn 6°, đã thử thật một lần co cả bàn tay rồi duỗi ở mức 52° cho index/middle: cả hai thao tác thành công, sai số khi xác nhận tương ứng 2,68° và 1,57°. Thời gian gồm theo dõi/giữ tư thế khoảng 19,4 và 21,2 giây; tốc độ đặt 20°/giây là mức trần, chưa phải tốc độ thực đạt liên tục. Tải tuyệt đối lớn nhất 285, nhiệt độ cao nhất 30°C; điện áp thấp nhất 4,4 V trong chế độ điện áp đã chọn. Không ghi EEPROM hay thay PID.

Theo yêu cầu mở thêm, đã thử riêng index/middle ở 42→44→46→48→50→52°, sau đó 54→56→58°, tốc độ 4°/giây với phản hồi ở mỗi bước. Cả bốn servo tới mục tiêu, status=0, sai lệch dưới 3°. Người dùng xác nhận mức 52° cải thiện rõ nhưng vẫn còn cong đốt cuối. Phản hồi servo ở mức 58° vẫn bình thường; độ thẳng của đốt cuối cần xác nhận bằng quan sát, không suy từ góc servo.

Người dùng xác nhận ở 58° chỉ index còn cong, middle đã thẳng. Chỉ tăng index qua 60° rồi 62°, giữ nguyên mục tiêu middle ở 58°. Ở index 62°: mục tiêu tuyệt đối ID 1–2 là -59°/+62°; phản hồi ban đầu -57,42°/+60,94°, status=0, tải tuyệt đối tối đa 120, nhiệt độ tối đa 31°C. Người dùng xác nhận index đã thẳng ở 62°.

Đã kiểm tra thêm một lượt co rồi duỗi toàn bộ bàn tay thật với profile cuối index 62°/middle 58° và tốc độ đặt 20°/giây: cả hai hoàn thành, sai số lớn nhất lúc xác nhận co 2,68°, duỗi 1,28°. Đọc lại cả tám servo đều status=0, giữ torque ở tư thế mở. Bộ kiểm tra phần mềm gồm 37 bài đều đạt, bao gồm mô hình servo chậm, servo đứng yên thật và trường hợp đứng yên giả do khoảng dẫn quỹ đạo quá nhỏ.

Mặc định dùng COM3. `OPEN_EXTENSIONS=(67,58,37,35)` đặt mức duỗi, `CLOSE_FLEXIONS=(92,90,90,90)` đặt mức co riêng cho index/middle/ring/thumb. Index đã được xác nhận thẳng ở 62°, middle ở 58°. Theo yêu cầu mới, index tăng riêng thêm 5° lên 67°, qua từng bước 62→64→66→67; middle giữ 58°. Đây là các góc tương đối của servo cộng với offset project, không phải góc khớp. Khung chỉnh phần mềm 35–70° chứa các mức đã thử, vẫn kiểm tra mục tiêu theo giới hạn servo thực đọc từ thiết bị; không coi khung này là giới hạn cơ khí của khớp. Tham số `DRY_RUN=True` trong cell khởi tạo chỉ kiểm tra kết nối/mục tiêu, không gửi lệnh điều khiển. Chế độ điện áp giống script đã thử: chỉ cho phép riêng cờ điện áp trong 4–7,4 V, giữ các kiểm tra lỗi khác, tải, nhiệt độ và phản hồi vị trí.

Đã bổ sung bốn cell thử chậm riêng index/middle ở hai tư thế co và duỗi, chỉ ghi lệnh vào đúng cặp servo của ngón chọn. Tốc độ thử riêng là 4°/giây; bảy tư thế thông thường vẫn dùng `SPEED_DEG_S`. Phản hồi hiển thị góc đặt, góc đo, sai lệch, tải thô, điện áp và trạng thái. Sai số xác nhận cuối hành trình đặt ở 4° (`END_TOLERANCE_DEG`), áp dụng thống nhất cho cả bảy tư thế và bốn cell thử riêng.

`hand.adjust_endpoint("index", "open", delta=1)` thử một bước chỉnh riêng tối đa 2°; cũng dùng được với `middle` và `close`. Chỉ cập nhật profile trong bộ nhớ sau khi tới mục tiêu; thất bại hoặc dry run không lưu góc mới. Muốn giữ qua lần khởi tạo tiếp theo, sửa tuple tương ứng trong cell đầu sau khi xác nhận bằng quan sát. Không ghi EEPROM hay thay `MiddlePos`.

Ở lần thử trước khi tăng mức duỗi: index/middle mở 42° vẫn hơi cong theo quan sát của người dùng. Index co 92° đạt sai số 2,42°; middle co 92° bị dừng vì ID 3 lệch 3,80°. Vì vậy giữ mức co middle ở 90°. Các lần hiệu chỉnh mới phía trên đã tăng mức duỗi độc lập tới khi người dùng xác nhận thẳng, không thay offset hoặc EEPROM và không kết luận chốt/thanh liên kết bị lỗi chỉ từ phản hồi servo.

JupyterLab và kernel đã được cài trong máy này. Để cài lại trên môi trường khác sau khi tạo `.venv`:

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-notebook.txt
.\.venv\Scripts\python.exe -m ipykernel install --user --name amazinghand --display-name "AmazingHand (.venv)"
```

Đã chạy toàn bộ 13 cell trên bàn tay thật sau sửa, gồm khởi tạo, bảy tư thế, bốn lần thử chậm riêng và nhả torque. 42 bài kiểm thử phần mềm cũng đạt. Xem [kết quả từng cell và phân tích lỗi](PythonExample/NOTEBOOK_CHECK_VI.md). Output chạy thật đã được lưu trong notebook; sau kiểm tra bàn tay được duỗi lại.

Nếu cell khởi tạo báo `Parsing error`, đây là lỗi giải mã phản hồi serial khi đọc servo, trước khi gửi mục tiêu chuyển động. Helper thử lại tối đa ba lần cho riêng lỗi này; lỗi model, điện áp, nhiệt độ và trạng thái servo vẫn được báo ngay. Nếu lỗi lặp lại, kiểm tra kết nối USB và nguồn bàn tay: rút cả hai, cắm lại nguồn rồi USB, kiểm tra lại cổng COM và chạy cell khởi tạo sau **Restart Kernel**. Windows nhận COM3 chỉ xác nhận adapter USB đang hiện diện, chưa xác nhận servo giao tiếp được. Phần theo dõi khi đang chuyển động vẫn dừng ngay khi đọc lỗi, không bỏ qua mẫu dữ liệu lỗi.

## Bắt đầu: mô phỏng 3D (khoảng 5–15 giây)

1. Mở PowerShell ở thư mục project:

   ```powershell
   cd C:\Users\Admin\Documents\AmazingHand
   ```

2. Chạy mô phỏng:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\run-demo.ps1
   ```

   Hai cửa sổ MuJoCo hiển thị bàn tay trái và phải tự động co/duỗi các ngón. Demo này không cần robot hay webcam. Nếu hai cửa sổ chồng lên nhau, kéo một cửa sổ sang bên cạnh.

3. Nhấn **Ctrl+C** trong PowerShell để dừng toàn bộ demo.

## Theo dõi bàn tay bằng webcam (khoảng 5–15 giây)

1. Dừng demo trước đó bằng **Ctrl+C**.
2. Chạy:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\run-demo.ps1 -Mode tracking
   ```

3. Đưa bàn tay vào khung hình **MediaPipe Hands**. Mô hình 3D tương ứng sẽ bám theo chuyển động; dùng nơi đủ sáng, nhìn rõ lòng bàn tay. Nhấn **Ctrl+C** trong PowerShell để dừng cả ba cửa sổ. Phím **q** trong cửa sổ webcam chỉ dừng node webcam.

## Môi trường đã cài

- Python **3.12.14**, môi trường riêng tại `.venv`, Dora CLI/API **0.3.13**.
- MuJoCo, Mink, Quadprog, NumPy/SciPy/PyArrow và các phụ thuộc của AHSimulation.
- MediaPipe **0.10.14**, OpenCV contrib **4.11.0.86** và các phụ thuộc của HandTracking.
- `rustypot` cho các ví dụ Python điều khiển servo thật; `onshape-to-robot` theo cấu hình của project.

`requirements-demo.lock` lưu phiên bản đã cài. Không cần kích hoạt `.venv`, chạy `dora up`, hay build lại để chạy hai demo trên. Script tự chọn đúng Python và Dora.

Muốn cài lại trên máy Windows có `uv`, chạy từ thư mục project:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-demo.ps1
```

Lần tải mới mất khoảng 2–5 phút tùy mạng. Script dùng Python 3.12; không ghi đè môi trường Python chung.

## Khi gặp lỗi

| Hiện tượng | Thao tác |
| --- | --- |
| Không thấy cửa sổ MuJoCo | Kiểm tra thanh taskbar hoặc Alt+Tab; cửa sổ có thể nằm phía sau PowerShell. |
| Webcam không mở | Đóng Camera/Zoom/Teams đang dùng camera; bật Settings → Privacy & security → Camera → Let desktop apps access your camera. |
| Webcam hiện hình nhưng tay 3D chưa chuyển động | Đưa toàn bộ bàn tay vào ảnh, tăng ánh sáng và giữ lòng bàn tay hướng về camera. |
| Thiếu thư viện | Chạy `setup-demo.ps1` như lệnh bên trên. |

Cảnh báo MediaPipe về feedback tensors hoặc Protobuf deprecated không làm dừng demo.

## Robot thật là bước riêng

Các lệnh phía trên chạy mô phỏng. Bàn tay thật đã kết nối thành công qua **USB-Enhanced-SERIAL CH343, COM3, 1.000.000 baud**. Đã đọc được đủ 8 servo SCS0009, ID 1–8; ngón đầu tiên (ID 1 và 2) đã cử động và quay về, được xác nhận bằng phản hồi vị trí.

### Duỗi toàn bộ bàn tay (đã kiểm thử)

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_HardwareDemo.py --port COM3 --open-hand
```

Lệnh chạy một lần, khoảng 20 giây: từng ngón đi chậm 8°/giây tới tư thế `OpenHand()` trong project, rồi giữ tư thế bằng torque. Đã kiểm thử đủ 8 servo; sai số lớn nhất đo được 2,19°. Đây là xác nhận vị trí servo, chưa thay thế việc quan sát xem các ngón đã duỗi thẳng về mặt cơ khí.

Các góc mục tiêu theo `MiddlePos` hiện có trong `PythonExample/AmazingHand_Demo.py`: **[-32, 35, -40, 27, -37, 40, -47, 35]°**, tương ứng ID 1–8. Nếu bàn tay của bạn dùng offset hiệu chỉnh khác, cập nhật `MiddlePos` hoặc truyền `--middle-pos` với đủ 8 giá trị theo độ. Không tự hiệu chỉnh EEPROM hay ghi lại ID servo.

Script lưu trạng thái trước khi duỗi trong `.tools/hardware/before-open-*.json`; kiểm tra tải, trạng thái lỗi, điện áp và độ lệch vị trí trong lúc chạy. Nếu bị ngắt hoặc gặp lỗi trong khi di chuyển, ngón đang chạy được nhả torque; các ngón đã hoàn tất vẫn giữ tư thế. Sau khi lệnh thành công, có thể nhả toàn bộ torque bằng:

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_HardwareDemo.py --port COM3 --release
```

Khi nhả torque, các ngón có thể dịch chuyển dưới trọng lượng của chính chúng.

### Co–duỗi từng ngón một lượt ở tốc độ thấp

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_HardwareDemo.py --port COM3 --cycle-hand
```

Để bàn tay trống và giữ tay khỏi cơ cấu. Lệnh chạy một lượt cho bốn ngón: mở theo `OpenHand`, co qua các mức 0°, 45°, 90° tương đối với `MiddlePos`, rồi mở lại. Tốc độ servo là 4°/giây, tổng thời gian khoảng 5 phút tùy vị trí ban đầu. Các góc là góc servo, không phải góc khớp ngón. Không chạy lặp vô hạn hoặc ghi EEPROM.

Trong khi di chuyển, script kiểm tra phản hồi vị trí, trạng thái lỗi, tải, nhiệt độ và điện áp của cặp servo đang chạy. Nếu có lỗi hoặc nhấn Ctrl+C, script cố tắt torque cả tám servo và dừng các ngón còn lại. Thành công sẽ giữ tư thế mở; vẫn cần quan sát để xác nhận các đốt ngón co–duỗi đúng. Nhả torque bằng `--release` khi không cần giữ tư thế.

Lượt thử sau khi người dùng sửa cách lắp index đã tới mục tiêu mở và hai mức co đầu tiên. Khi tiến tới mức 90°, ID 2 báo `status=1`, điện áp 4,4 V dưới giới hạn cấu hình 4,5 V; bài test dừng trước ba ngón còn lại. Đã đọc lại và xác nhận cả tám servo tắt torque, ID 2 trở về 4,6 V và `status=0`. Chưa xác nhận được một lượt co–duỗi hoàn chỉnh. Cần kiểm tra đường cấp nguồn trước khi chạy lại; không hạ ngưỡng điện áp để bỏ qua lỗi.

### Duỗi toàn bộ, rồi đồng thời nắm–duỗi năm lần

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_GripCycles.py --port COM3 --cycles 5
```

Lệnh gửi đồng bộ mục tiêu cho cả tám servo: mở cả bốn ngón trước, rồi nắm–mở năm lần liên tiếp ở 4°/giây. Hoàn thành sẽ giữ tư thế mở. Mỗi bước kiểm tra cả tám servo; khi điện áp/tải/nhiệt độ/trạng thái hoặc sai lệch vị trí vượt giới hạn, dừng ngay và cố tắt torque tất cả. Thời gian khoảng sáu phút nếu không có lỗi. Có thể đọc kiểm tra mà không gửi lệnh bằng `--dry-run`.

Đã kiểm tra logic bằng bốn bài test dùng servo giả: năm lượt kết thúc mở, sụt áp dừng và nhả toàn bộ, Ctrl+C nhả toàn bộ, và dry-run không gửi lệnh. Lượt chạy phần cứng theo yêu cầu năm lần đã dừng ngay ở bước mở ban đầu vì ID 2 đo 4,4 V, dưới giới hạn 4,5 V; **chưa hoàn thành lượt nào**. Không bỏ qua giới hạn để tiếp tục chạy khi nguồn chưa ổn định.

Theo yêu cầu chẩn đoán của người dùng, đã thêm tùy chọn `--ignore-low-voltage` để bỏ riêng điều kiện dừng do điện áp thấp trong script cho một lần chạy; mặc định vẫn kiểm tra điện áp. Tùy chọn không ghi cấu hình servo và vẫn kiểm tra trạng thái báo lỗi, điện áp cao, tải, nhiệt độ, giới hạn góc và phản hồi vị trí. Hai bài test giả bổ sung xác nhận có thể hoàn thành năm lượt khi chỉ điện áp thấp và vẫn dừng/nhả toàn bộ khi servo báo lỗi. Khi chạy thật với tùy chọn này, cả bốn ngón bắt đầu mở đồng thời rồi ID 2 báo `status=1`, điện áp 4,4 V; lệnh dừng, chưa hoàn thành lượt nào. Bỏ riêng ngưỡng phần mềm chưa đủ để hoàn thành bài test; cần kiểm tra đường cấp nguồn và báo lỗi của servo.

Người dùng xác nhận adapter **5 V–5 A** và không có đồng hồ đo. Đọc cấu hình cho thấy cả tám servo có `min_voltage_limit=45`, `unloading_condition=32`, `led_alarm_condition=37`. Tài liệu [FEETECH SCS0009](https://www.feetechrc.com/6v-23kg-serial-bus-steering-gear_65522.html) và [SCS0009-C013, trang 3](https://www.feetechrc.com/Data/feetechrc/upload/file/20220421/6378615864121461222946681.pdf) ghi dải đầu vào 4–7,4 V. Không thể kết luận adapter thiếu dòng chỉ dựa trên nhãn hoặc cảnh báo tại 4,4 V.

Đã thêm chế độ chẩn đoán `--allow-voltage-warning`: cho qua **riêng bit điện áp 0x01** khi số đo còn trong 4–7,4 V; các bit khác, tải, nhiệt độ, giới hạn góc và sai lệch vị trí vẫn kiểm tra. Chế độ không thay đổi cấu hình servo hoặc ghi EEPROM; không được hiểu là bỏ toàn bộ bảo vệ. Mặc định script vẫn giữ cách kiểm tra nghiêm ngặt ban đầu. Tám bài test giả đã kiểm tra thêm việc cho qua riêng cờ điện áp, dừng khi có cờ khác đi kèm hoặc điện áp ra ngoài dải hãng.

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_GripCycles.py --port COM3 --cycles 5 --allow-voltage-warning
```

Lượt đầu với chế độ cho phép cảnh báo điện áp hoàn thành hai chu kỳ rồi dừng ở cuối bước nắm thứ ba: ID 3 lệch 3,26° so với mục tiêu 85°, tải đo −195, nhiệt độ 29°C, không có cờ lỗi. Thêm `--end-tolerance 4` để xác nhận cuối bước trong 4° thay cho mặc định 3°; mức dừng khi di chuyển vẫn là 8°. Một bài test giả bổ sung tái hiện sai số dư 3,26°, xác nhận mặc định dừng còn chế độ 4° có thể hoàn thành. Tổng cộng chín bài test giả đã đạt.

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_GripCycles.py --port COM3 --cycles 5 --allow-voltage-warning --end-tolerance 4
```

**Kết quả chạy thật với lệnh trên: hoàn thành đủ 5/5 chu kỳ liên tiếp**, sau bước mở ban đầu, trong khoảng 354 giây. Log xác nhận chuỗi mục tiêu `open, close, open, close, open, close, open, close, open, close, open`. Cuối lượt, sai số vị trí lớn nhất 1,91°; đọc lại cả tám servo đều đang bật torque giữ tư thế mở và `status=0`. Nhiệt độ cao nhất cả lượt 31°C, tải tuyệt đối cao nhất 315 (giá trị thanh ghi, không phải dòng điện), điện áp báo thấp nhất 4,3 V; không có mẫu trạng thái mang bit lỗi ngoài điện áp. Các số liệu này xác nhận chuyển động servo, vẫn cần người dùng quan sát các đốt ngón. Log và bản tóm tắt lưu tại `.tools/hardware/grip-feedback-1791520007715398200.jsonl` và `.tools/hardware/grip-summary-1791520007715398200.json`.

### Co cả bốn ngón và giữ tư thế nắm

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_GripCycles.py --port COM3 --close-hold --allow-voltage-warning --end-tolerance 4
```

Đưa đồng thời tám servo từ vị trí hiện tại tới tư thế `CloseHand` của demo ở 4°/giây rồi giữ torque, không tự mở lại. Mức co là góc tương đối +90°/−90° cộng `MiddlePos`, tương ứng mục tiêu ID 1–8: `[93, -90, 85, -98, 88, -85, 78, -90]°`. Đây là tư thế nắm trong project, chưa phải phép đo giới hạn cơ khí tuyệt đối của từng ngón. Các kiểm tra chẩn đoán giống bài test năm lượt vẫn hoạt động; có lỗi sẽ cố nhả torque cả tám servo. Nhả bằng lệnh `--release` của `AmazingHand_HardwareDemo.py` khi cần.

Đã chạy thật và xác nhận cả tám servo tới mục tiêu, sai lệch lớn nhất 2,97°, giữ tư thế trong hai giây kiểm tra rồi để torque bật. Đã thêm bài test giả xác nhận chế độ co–giữ không tự mở hoặc chạy chu kỳ; tổng cộng mười bài test giả đạt.

### Duỗi cả bốn ngón đồng thời và giữ tư thế mở

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_GripCycles.py --port COM3 --open-hold --allow-voltage-warning --end-tolerance 4
```

Di chuyển đồng thời từ vị trí hiện tại tới `OpenHand` đã kiểm thử rồi giữ torque, không tự nắm lại hoặc chạy chu kỳ. Mục tiêu ID 1–8: `[-32, 35, -40, 27, -37, 40, -47, 35]°`; tốc độ 4°/giây và các kiểm tra chẩn đoán giữ nguyên. Đã chạy thật từ tư thế nắm: cả tám servo tới mục tiêu, sai lệch lớn nhất 1,91°, giữ tư thế mở trong hai giây kiểm tra rồi để torque bật. Xác nhận độ thẳng của các khớp bằng quan sát, không suy ra giới hạn cơ khí tuyệt đối từ số đo servo. Đã thêm bài test giả xác nhận mở từ tư thế nắm và không chạy chu kỳ; tổng cộng mười một bài test giả đạt.

### Tăng mức duỗi nhỏ cho ba ngón, giữ nguyên ngón cái

Khi người dùng xác nhận ngón cái đã mở đủ nhưng ba ngón còn lại chưa thẳng, đã thử riêng một bước tăng góc duỗi từ 35° lên 37° cho servo ID 1–6:

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_HardwareDemo.py --port COM3 --open-three --extension 37 --allow-voltage-warning
```

Lệnh chạy lần lượt ba ngón ở 4°/giây, không ghi bất kỳ mục tiêu/tốc độ/torque nào vào ID 7–8. Mục tiêu mới ID 1–6: `[-34, 37, -42, 29, -39, 42]°`. Đã chạy thật: sai lệch lớn nhất 1,57°; đọc lại mục tiêu ngón cái vẫn ở mức mở cũ. Chưa xác nhận ba ngón thẳng bằng quan sát; cần người dùng cho biết ngón và đốt còn cong trước khi tăng tiếp. Không thay `MiddlePos`, không lưu 37° làm mặc định, không ghi EEPROM. Các kiểm tra tải, nhiệt độ, phản hồi vị trí và bit lỗi ngoài điện áp giữ nguyên; cờ điện áp chỉ được phép trong 4–7,4 V. Hai bài test giả thêm xác nhận không gửi lệnh tới ngón cái và dừng/nhả cặp đang chạy khi có lỗi khác; tổng cộng mười ba bài test giả đạt.

Người dùng sau đó chỉ ra index và middle còn chưa thẳng. Đã gọi helper `open_hand` riêng với `fingers=(1, 2), extension=39, speed=4, allow_voltage_warning=True` để tăng thêm một bước 2° cho ID 1–4, không gửi lệnh tới ID 5–8. Mục tiêu mới ID 1–4: `[-36, 39, -44, 31]°`; phản hồi đo `[-34,57, 37,79, -42,19, 29,59]°`, sai lệch lớn nhất 1,81°. Giữ nguyên mục tiêu ngón áp út ở bước 37° và ngón cái ở bước 35°. Đây vẫn là tư thế cần xác nhận bằng quan sát, chưa thay mặc định hoặc nhận là giới hạn duỗi cơ khí.

### Dấu V / peace

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_VSign.py --port COM3 --allow-voltage-warning
```

Index và middle giơ/tách ra, ring và thumb co xuống; chạy một lần chậm rồi giữ tư thế. Xem tùy chọn độ tách, bàn tay trái, chế độ chỉ đọc và nhả torque trong [hướng dẫn dấu V](PythonExample/V_SIGN_VI.md).

### Kiểm tra hoặc thử cử động nhỏ

Nếu index chưa duỗi đủ ở tư thế mặc định, có thể thử riêng tư thế `Index_Pointing` của project, chỉ gửi lệnh tới servo ID 1–2:

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_HardwareDemo.py --port COM3 --open-finger 1 --extension 40
```

Mục tiêu là **[-37, 40]°** theo `MiddlePos` hiện có, lớn hơn mức duỗi mặc định 5° mỗi servo. Đã thử trên phần cứng: phản hồi khoảng **[-36,04, 38,96]°**; cần quan sát người dùng để xác nhận index thực sự đã thẳng. Trong lúc giữ tư thế, có một mẫu `status=1` ở ID 2 rồi trở lại 0, với điện áp khoảng 4,5–4,6 V so với giới hạn thấp đã cấu hình là 4,5 V. Chưa kết luận nguyên nhân của mẫu trạng thái này; chưa tăng góc tiếp. Lệnh không tự sửa `MiddlePos` hoặc ghi EEPROM. Lệnh `--open-hand` vẫn dùng tư thế mặc định 35°; hiệu chỉnh góc phù hợp với riêng bàn tay cần được xác nhận bằng quan sát trước khi lưu làm mặc định.

Script kiểm tra phần cứng mới (chỉ đọc, không làm servo chuyển động):

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_HardwareDemo.py --port COM3
```

Sau khi đọc được hai servo ID 1 và 2, thử ngón đầu tiên lệch 3° rồi quay về:

```powershell
.\.venv\Scripts\python.exe .\PythonExample\AmazingHand_HardwareDemo.py --port COM3 --move-finger 1
```

Script xác minh model SCS0009, đọc giới hạn góc, điện áp, nhiệt độ và trạng thái lỗi trước khi gửi lệnh. Chuyển động dùng vị trí hiện tại, tốc độ đặt 15°/giây và mục tiêu lệch 3°; kết quả chỉ báo `MOVEMENT_CONFIRMED` khi phản hồi vị trí xác nhận cả hai servo đã di chuyển và quay về trong sai số 2°. Nếu bị ngắt hoặc gặp lỗi trong khi thử chuyển động, script cố tắt torque ở ngón đang thử. Sau một lần thử thành công, torque và tốc độ được khôi phục như trước. Lần kiểm thử thực tế đo được ID 1 lệch +1,17°, ID 2 lệch −1,46°; chuyển động thực tế có thể nhỏ hơn mục tiêu do vùng chết của servo và cơ cấu cơ khí.

Để thử một ngón khác, thay `--move-finger 1` bằng `2`, `3` hoặc `4`; mỗi lần chỉ thử một ngón. Tham số này giả định các cặp ID được lắp theo project: (1,2), (3,4), (5,6), (7,8).

Nếu báo bài thử 3° không xác nhận được chuyển động, script đã đặt lại mục tiêu ban đầu và cố nhả torque ở ngón thử. Bài thử yêu cầu cả hai servo di chuyển ít nhất 0,7° đúng chiều lệnh; chuyển động nhỏ hơn, như 0,29°, không đạt điều kiện này. Thông báo này tự nó chưa chứng minh servo hỏng. Dùng `--open-hand` để đưa cả bàn tay về tư thế duỗi thay vì lặp bài thử nhỏ.

Nếu Windows lại báo `A device attached to the system is not functioning`, rút/cắm lại USB vào cổng khác trước khi chạy lại. Lỗi này đã hết sau khi đổi cổng USB trong lần kiểm tra thực tế.

1. Kết nối bàn tay SCS0009 và USB serial bus driver; cấp nguồn theo tài liệu phần cứng của project.
2. Mở `PythonExample/AmazingHand_Demo.py`, thay `serial_port="COM11"` bằng cổng của USB driver trong Device Manager. Đặt `Side` và `MiddlePos` theo bàn tay đã hiệu chỉnh.
3. Sau khi hoàn tất cấu hình, chạy:

   ```powershell
   .\.venv\Scripts\python.exe .\PythonExample\AmazingHand_Demo.py
   ```

Demo nâng cao điều khiển robot trong `Demo/AHControl` còn cần Rust/Cargo và công cụ biên dịch C++ trên Windows. Chưa cài/build nhánh này; cấu hình dataflow gốc dùng cổng Linux `/dev/ttyACM0`, cần đổi sang cổng COM và hiệu chỉnh `Demo/AHControl/config/r_hand.toml` trước khi sử dụng.

Tài liệu gốc: [Demo/README.md](Demo/README.md). Dora CLI 0.3.13 có thể cài qua [gói chính thức dora-rs-cli](https://pypi.org/project/dora-rs-cli/0.3.13/); Python được quản lý bằng [uv](https://docs.astral.sh/uv/guides/install-python/).
