"""Camera, RPS H5 và adapter cho phiên kéo-búa-bao trong notebook."""

from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
import random
from pathlib import Path
import threading
import time
import uuid

MOVES = ('rock', 'paper', 'scissors')
UNKNOWN = 'UNKNOWN'
COUNTER_MOVE = {'rock': 'paper', 'paper': 'scissors', 'scissors': 'rock'}


@dataclass
class GameConfig:
    """Các mặc định motor được lấy từ notebook RPS đang có, không ghi EEPROM."""
    camera_id: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 30
    confidence_threshold: float = .75
    smoothing_window: int = 5
    minimum_agreement: int = 4
    countdown_seconds: float = 3
    gesture_timeout_seconds: float = 3
    snapshot_delay_seconds: float = .25
    robot_enabled: bool = True
    # ROI theo tỷ lệ (trái, trên, phải, dưới); đặt bàn tay robot ở ngoài vùng này.
    roi: tuple = (.03, .05, .58, .95)
    preview_seconds: float = 12
    display_backend: str = 'auto'  # auto/opencv/notebook; notebook dùng một output duy nhất.
    display_fps: float = 15
    result_seconds: float = 2
    camera_timeout_seconds: float = 1
    motor_timeout_seconds: float = 30
    port: str = 'COM3'
    speed_deg_s: float = 160
    open_extensions: tuple = (70, 60, 37, 35)
    close_flexions: tuple = (92, 90, 90, 90)
    end_tolerance: int = 4
    allow_voltage_warning: bool = True
    motion_profile: str = 'fast'
    reset_move: str = 'rock'
    device: str = 'auto'
    offline: bool = False
    log_path: str = 'logs/rps_rounds.jsonl'
    window_width: int = 1920
    window_height: int = 1080
    target_wins: int = 3
    require_confirmation: bool = True
    show_confirmation_buttons: bool = False
    laya_exploration: float = .30
    rps_model_path: str = 'models/rps.h5'
    # training-hand.ipynb: flow_from_directory sắp tên thư mục theo alphabet.
    rps_class_names: tuple = ('paper', 'rock', 'scissors')
    rps_pixel_scale: float = 1/255
    prediction_margin: float = .15
    minimum_roi_std: float = 8

    def validate(self):
        numeric = (self.camera_width, self.camera_height, self.camera_fps,
                   self.display_fps,
                   self.gesture_timeout_seconds, self.camera_timeout_seconds,
                   self.motor_timeout_seconds)
        if any(not math.isfinite(x) or x <= 0 for x in numeric):
            raise ValueError('Kích thước, FPS và timeout phải là số dương hữu hạn.')
        if not 0 < self.confidence_threshold <= 1:
            raise ValueError('confidence_threshold phải nằm trong (0, 1].')
        if not 1 <= self.minimum_agreement <= self.smoothing_window or self.minimum_agreement <= self.smoothing_window / 2:
            raise ValueError('minimum_agreement phải là đa số và không vượt smoothing_window.')
        if any(not math.isfinite(x) or x < 0 for x in (self.countdown_seconds, self.preview_seconds, self.result_seconds, self.snapshot_delay_seconds)):
            raise ValueError('Thời gian countdown/preview/kết quả không được âm.')
        x1, y1, x2, y2 = self.roi
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError('ROI cần 0 ≤ trái < phải ≤ 1 và 0 ≤ trên < dưới ≤ 1.')
        if self.display_backend not in ('auto', 'opencv', 'notebook') or self.reset_move not in MOVES:
            raise ValueError('display_backend hoặc reset_move không hợp lệ.')
        if self.target_wins != 3 or self.window_width < 960 or self.window_height < 540:
            raise ValueError('Trận chạm 3 điểm thắng; cửa sổ tối thiểu 960×540.')
        if len(self.rps_class_names) != 3 or set(self.rps_class_names) != set(MOVES):
            raise ValueError('rps_class_names phải chứa đủ paper, rock, scissors theo thứ tự train.')
        if not 0 <= self.prediction_margin < 1 or self.minimum_roi_std < 0:
            raise ValueError('Ngưỡng margin/độ tương phản không hợp lệ.')
        if not math.isfinite(self.rps_pixel_scale) or self.rps_pixel_scale <= 0:
            raise ValueError('rps_pixel_scale phải dương hữu hạn.')
        if not math.isfinite(self.laya_exploration) or not 0 <= self.laya_exploration <= 1:
            raise ValueError('laya_exploration phải nằm trong [0,1].')
        return self


class RPSModelSession:
    """Load H5 một lần bằng Keras 3/PyTorch; tiền xử lý đúng notebook train."""
    def __init__(self, model_path, config):
        import numpy as np
        self.config = config.validate()
        self.path = Path(model_path)
        if not self.path.is_file():
            raise FileNotFoundError(f'Không tìm thấy model local: {self.path}')
        os.environ['KERAS_BACKEND'] = 'torch'
        import keras
        if keras.backend.backend() != 'torch':
            raise RuntimeError('Keras đã import với backend khác. Restart Kernel và chạy lại Cell 1.')
        self.keras = keras
        self.model = keras.models.load_model(str(self.path), compile=False)
        if tuple(self.model.input_shape) != (None, 150, 150, 3) or tuple(self.model.output_shape) != (None, 3):
            raise ValueError('Model cần input (None,150,150,3), output (None,3).')
        self.closed = False
        self.infer(np.zeros((1,150,150,3), np.float32))  # Warmup một lần.

    def infer(self, batch):
        import numpy as np
        import torch
        if self.closed:
            raise RuntimeError('Model RPS đã đóng. Chạy lại Cell 3, 5 và 8.')
        with torch.inference_mode():
            output = self.model(batch, training=False)
            probabilities = np.asarray(self.keras.ops.convert_to_numpy(output), dtype=np.float32)
        if (probabilities.shape != (1,3) or not np.isfinite(probabilities).all()
                or (probabilities < 0).any() or (probabilities > 1).any()
                or not np.isclose(probabilities.sum(), 1, atol=.01)):
            raise RuntimeError('Model RPS trả xác suất không hợp lệ.')
        return probabilities[0]

    def close(self):
        if not self.closed:
            self.model = None
            self.closed = True


class CameraStream:
    """Luôn hút frame mới trong luồng nền; round không dùng frame tồn từ countdown."""
    def __init__(self, config):
        self.config = config
        self.capture = None
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = None
        self.sequence = 0
        self.latest = None
        self.failures = 0
        self.closed = True

    def open(self):
        import cv2
        if not self.closed:
            return self
        self.config.validate()
        backend = cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.config.camera_id, backend)
        if not cap.isOpened():
            cap.release()
            cap = None
            for index in range(4):
                if index == self.config.camera_id:
                    continue
                probe = cv2.VideoCapture(index, backend)
                if probe.isOpened():
                    ok, frame = probe.read()
                    if ok and frame is not None:
                        cap = probe
                        print(f'Camera {self.config.camera_id} không có; tự chọn camera {index}.')
                        self.config.camera_id = index
                        break
                probe.release()
            if cap is None:
                raise RuntimeError('Không tìm thấy camera đọc được ảnh (đã kiểm tra index 0–3). '
                                   'Cắm webcam, cấp quyền camera và đóng app đang chiếm webcam, rồi chạy lại Cell 4.')
        for key, value in ((cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_width),
                           (cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_height),
                           (cv2.CAP_PROP_FPS, self.config.camera_fps), (cv2.CAP_PROP_BUFFERSIZE, 1)):
            cap.set(key, value)
        self.capture = cap
        self.closed = False
        self.latest = None
        self.failures = 0
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True, name='AmazingHand-camera')
        self.thread.start()
        try:
            frame, _, _ = self.get_frame(timeout=3)
        except BaseException:
            self.close()
            raise
        print(f'PASS — Camera {self.config.camera_id}: {frame.shape[1]}×{frame.shape[0]}, '
              f'FPS thiết bị báo {cap.get(cv2.CAP_PROP_FPS):.1f}')
        return self

    def _capture_loop(self):
        try:
            while not self.stop_event.is_set():
                ok, frame = self.capture.read()
                captured = time.monotonic()
                with self.condition:
                    if ok and frame is not None:
                        self.sequence += 1
                        self.latest = (frame, captured, self.sequence)
                        self.failures = 0
                    else:
                        self.failures += 1
                    self.condition.notify_all()
                if not ok:
                    self.stop_event.wait(.03)
        except Exception:
            with self.condition:
                self.failures = 10
                self.condition.notify_all()

    def get_frame(self, timeout=None, after_sequence=-1, min_time=0):
        timeout = self.config.camera_timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + timeout
        with self.condition:
            while not self.closed:
                if self.failures >= 5:
                    raise RuntimeError('Camera mất frame liên tiếp. Kiểm tra USB/quyền truy cập webcam.')
                if self.latest is not None:
                    frame, captured, seq = self.latest
                    if seq > after_sequence and captured >= min_time and time.monotonic() - captured <= timeout:
                        return frame.copy(), captured, seq
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Camera không trả frame mới trong thời gian cho phép.')
                self.condition.wait(min(.05, remaining))
        raise RuntimeError('Camera đã đóng. Chạy lại Cell 8.')

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.capture is not None:
            self.capture.release()
        self.capture = None
        self.latest = None


@dataclass
class GestureObservation:
    move: str = UNKNOWN
    raw_move: str = UNKNOWN
    label: str = 'None'
    confidence: float = 0
    latency_ms: float = 0
    processing_fps: float = 0
    probabilities: dict = field(default_factory=dict)
    reason: str = ''
    single_frame: bool = False


class GestureDetector:
    """CNN phân loại ROI, lọc confidence/margin và đồng thuận theo thời gian."""
    def __init__(self, session, config):
        self.session, self.config = session, config
        self.buffer = deque(maxlen=config.smoothing_window)
        self.last_process_time = None

    def reset(self):
        self.buffer.clear()
        self.last_process_time = None

    def accept(self, probabilities, single_frame=False):
        import numpy as np
        values = np.asarray(probabilities, dtype=float)
        obs = GestureObservation()
        if (values.shape != (3,) or not np.isfinite(values).all() or (values < 0).any()
                or (values > 1).any() or not np.isclose(values.sum(), 1, atol=.01)):
            self.reset()
            obs.reason = 'Xac suat model khong hop le'
            return obs
        index = int(values.argmax())
        candidate = self.config.rps_class_names[index]
        score = float(values[index])
        obs.label, obs.confidence = candidate, score
        obs.probabilities = dict(zip(self.config.rps_class_names, values.tolist()))
        margin = score-float(np.sort(values)[-2])
        if score < self.config.confidence_threshold or margin < self.config.prediction_margin:
            self.buffer.append((UNKNOWN, 0))
            obs.reason = f'Confidence {score:.0%} / margin {margin:.0%} thap'
            return obs
        obs.raw_move = candidate
        if single_frame:
            obs.move = candidate
            return obs
        self.buffer.append((candidate, score))
        votes = [confidence for move, confidence in self.buffer if move == candidate]
        if len(self.buffer) == self.config.smoothing_window and len(votes) >= self.config.minimum_agreement:
            obs.move, obs.confidence = candidate, sum(votes)/len(votes)
        else:
            obs.reason = f'Dang xac nhan {len(votes)}/{self.config.minimum_agreement}'
        return obs

    def process(self, frame, single_frame=False):
        import cv2
        import numpy as np
        from PIL import Image
        if frame is None or getattr(frame, 'size', 0) == 0:
            self.reset()
            return GestureObservation(reason='Camera mat frame')
        started = time.perf_counter()
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = self.config.roi
        crop = frame[int(y1*h):int(y2*h), int(x1*w):int(x2*w)]
        if not crop.size:
            raise ValueError('ROI rong; chinh ROI tai Cell 2.')
        # load_img/flow_from_directory trong notebook train dùng RGB + nearest.
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb).resize((150,150), Image.Resampling.NEAREST)
        batch = np.asarray(image, dtype=np.float32)[None] * self.config.rps_pixel_scale
        if float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).std()) < self.config.minimum_roi_std:
            self.reset()
            obs = GestureObservation(reason='ROI phang / toi: kiem tra camera va ban tay')
        else:
            obs = self.accept(self.session.infer(batch), single_frame=single_frame)
        obs.latency_ms = (time.perf_counter()-started)*1000
        obs.single_frame = single_frame
        obs.processing_fps = (1/(started-self.last_process_time) if self.last_process_time is not None
                              and started > self.last_process_time else 1000/max(.001, obs.latency_ms))
        self.last_process_time = started
        return obs


class GameDisplay:
    """OpenCV với phím Q/Esc; phương án notebook chỉ cập nhật một ảnh JPEG."""
    def __init__(self, config):
        self.config = config
        self.backend = config.display_backend
        self.handle = None
        self.last_display = 0
        self.last_frame_time = None
        self.fps = 0
        self.window_open = False
        self.window_name = 'AmazingHand | RPS Arena'
        self.match_active = False
        self.button_text = ''
        self.clicked = False
        self.match_index = 1
        self.confirming = False
        self.confirmed_move = None
        self.app_active = False
        self.action = None
        self.allow_reset = False
        self.enter_prompt = ''

    def start_round(self):
        # Jupyter xóa output khi chạy lại cell: không update display_id của lượt cũ.
        if not self.app_active:
            self.handle = None
        self.last_display = 0
        self.last_frame_time = None

    def show(self, frame, state, observation=None, human=UNKNOWN, robot='LOCKED',
             result='', scores=None, extra='', force=False):
        import cv2
        now = time.monotonic()
        if not force and now-self.last_display < 1/self.config.display_fps:
            return
        self.last_display = now
        if self.last_frame_time is not None:
            instant = 1/max(1e-6, now-self.last_frame_time)
            self.fps = instant if not self.fps else .8*self.fps + .2*instant
        self.last_frame_time = now
        canvas = frame.copy()
        h, w = canvas.shape[:2]
        x1, y1, x2, y2 = self.config.roi
        cv2.rectangle(canvas, (int(x1*w), int(y1*h)), (int(x2*w), int(y2*h)), (0, 220, 0), 2)
        # Bảng điều khiển 16:9, camera bên trái và thông tin trận bên phải.
        import numpy as np
        width, height = self.config.window_width, self.config.window_height
        board = np.full((height, width, 3), (24, 19, 16), dtype=np.uint8)
        def text(value, x, y, size=.8, color=(235, 235, 235)):
            cv2.putText(board, str(value), (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                        size, color, 2, cv2.LINE_AA)
        text('AMAZINGHAND', 50, 70, 1.35, (230, 210, 80))
        text('ROCK / PAPER / SCISSORS', 50, 112, .65)
        text(f'VAN {self.match_index} | CHAM {self.config.target_wins} THANG', width-570, 80, .8)
        if self.app_active:
            self.allow_reset = state in ('READY', 'RESULT', 'MATCH_OVER')
            for left, right, label, enabled in (
                    (width-550, width-270, 'RESET GAME [R]', self.allow_reset),
                    (width-250, width-40, 'THOAT [Q]', True)):
                cv2.rectangle(board, (left,100), (right,145),
                              (95,75,45) if enabled else (45,40,35), -1)
                text(label, left+12,131,.57, (235,235,235) if enabled else (110,110,110))
        vw, vh = int(width*.66), int(height*.73)
        factor = min(vw/w, vh/h)
        image = cv2.resize(canvas, (int(w*factor), int(h*factor)))
        ox, oy = 40+(vw-image.shape[1])//2, 155+(vh-image.shape[0])//2
        board[oy:oy+image.shape[0], ox:ox+image.shape[1]] = image
        sx = int(width*.71)
        title = {'READY': 'SAN SANG', 'COUNTDOWN': 'CHUAN BI', 'COMMIT': 'DA KHOA NUOC',
                 'REVEAL': 'RA TAY!', 'VALIDATE': 'XAC NHAN', 'RESULT': 'KET QUA',
                 'RESET': 'VE TU THE CHO', 'PREVIEW': 'KIEM TRA CAMERA',
                 'MATCH_OVER': 'KET THUC TRAN', 'ERROR': 'LOI PHIEN GAME'}.get(state, state)
        text(title, sx, 205, .9, (230, 210, 80))
        text(extra[:38], sx, 255, .62)
        if state == 'COUNTDOWN':
            cv2.putText(board, extra, (ox+image.shape[1]//2-60, oy+image.shape[0]//2),
                        cv2.FONT_HERSHEY_SIMPLEX, 4, (230, 230, 80), 8, cv2.LINE_AA)
        text('BAN', sx, 350, .65)
        text(human.upper(), sx, 405, 1.1)
        text('AMAZINGHAND', sx, 485, .65)
        text(robot.upper(), sx, 540, 1.1)
        outcome = {'HUMAN_WIN': 'BAN THANG', 'ROBOT_WIN': 'ROBOT THANG',
                   'DRAW': 'HOA', 'INVALID_ROUND': 'CHUA NHAN DIEN - CHOI LAI'}.get(result, result)
        text(outcome, sx, 620, .65, (100, 225, 150))
        if observation and self.confirming:
            text(f'Model: {observation.label} {observation.confidence:.0%}', sx, 580, .6)
        if observation and not self.confirming:
            text(f'{observation.label}  {observation.confidence:.0%}', 50, height-115, .7)
            timing = (f'ANH DA CHUP | H5 {observation.latency_ms:.0f} ms' if observation.single_frame
                      else f'{observation.processing_fps:.0f} FPS | {observation.latency_ms:.0f} ms')
            text(timing,
                 50, height-80, .65)
            text(observation.reason, 470, height-80, .65, (100, 190, 250))
        if scores:
            text(f'BAN   {scores.get("human", 0)}', sx, 710, .9)
            text(f'ROBOT {scores.get("robot", 0)}', sx, 760, .9)
            text(f'HOA   {scores.get("draw", 0)}', sx, 810, .9)
            for player, y in (('human',700), ('robot',750)):
                for index in range(self.config.target_wins):
                    cv2.circle(board,(width-150+index*35,y),11,
                               (100,225,150) if scores.get(player,0)>index else (70,65,60),-1)
        text('Dat tron ban tay trong ROI | Q / Esc: dung', 50, height-45, .7)
        if self.button_text:
            cv2.rectangle(board, (sx, height-155), (width-40, height-75), (175, 115, 35), -1)
            text(self.button_text, sx+20, height-105, .85)
        if self.enter_prompt:
            text(self.enter_prompt, sx, height-110, .68, (100,225,150))
        if self.confirming:
            hint = f'DA CHON: {self.confirmed_move.upper()}' if self.confirmed_move else 'XAC NHAN: 1:R / 2:P / 3:S'
            text(hint, sx, height-165, .65, (100,225,150))
        if self.confirming and self.config.show_confirmation_buttons:
            text('XAC NHAN NUOC CUA BAN:', 50, height-150, .65, (100, 225, 150))
            for index, label in enumerate(('1: ROCK', '2: PAPER', '3: SCISSORS')):
                left = 50 + index*225
                cv2.rectangle(board, (left, height-135), (left+210, height-85), (175, 115, 35), -1)
                text(label, left+15, height-102, .6)
        canvas = board
        if self.backend == 'auto':
            # Tránh Qt kết thúc cả kernel trên Linux không có màn hình.
            self.backend = 'opencv' if os.name == 'nt' or os.environ.get('DISPLAY') else 'notebook'
        if self.backend == 'opencv':
            try:
                if not self.window_open:
                    cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(self.window_name, self.config.window_width, self.config.window_height)
                    cv2.setMouseCallback(self.window_name, self._mouse)
                    self.window_open = True
                cv2.imshow(self.window_name, canvas)
                key = cv2.waitKey(1) & 255
                if self.app_active and self.action == 'quit':
                    raise KeyboardInterrupt
                if self.app_active and self.allow_reset and key in (ord('r'),ord('R')):
                    self.action = 'reset'
                if self.enter_prompt and key == 13:
                    self.clicked = True
                if self.confirming and self.confirmed_move is None and key in (ord('1'), ord('2'), ord('3')):
                    self.confirmed_move = MOVES[key-ord('1')]
                if key in (13, 32) and self.button_text:
                    self.clicked = True
                if key in (27, ord('q'), ord('Q')) or cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                    raise KeyboardInterrupt
                return
            except cv2.error:
                self.close_window()
                self.backend = 'notebook'
                print('OpenCV không mở được cửa sổ; chuyển sang ảnh trong notebook.')
        from IPython.display import Image, display
        ok, encoded = cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if not ok:
            raise RuntimeError('Không mã hóa được frame hiển thị.')
        item = Image(data=encoded.tobytes())
        if self.handle is None:
            self.handle = display(item, display_id=True)
        else:
            self.handle.update(item)

    def _mouse(self, event, x, y, flags, userdata):
        import cv2
        if self.app_active and event == cv2.EVENT_LBUTTONUP and 100 <= y <= 145:
            width = self.config.window_width
            if width-550 <= x <= width-270 and self.allow_reset:
                self.action = 'reset'
            elif width-250 <= x <= width-40:
                self.action = 'quit'
            return
        if event == cv2.EVENT_LBUTTONUP and self.confirming and self.confirmed_move is None and self.config.show_confirmation_buttons:
            for index, move in enumerate(MOVES):
                if 50+index*225 <= x <= 260+index*225 and self.config.window_height-135 <= y <= self.config.window_height-85:
                    self.confirmed_move = move
                    return
        if (event == cv2.EVENT_LBUTTONUP and self.button_text
                and int(self.config.window_width*.71) <= x <= self.config.window_width-40
                and self.config.window_height-155 <= y <= self.config.window_height-75):
            self.clicked = True

    def begin_confirmation(self):
        self.confirming, self.confirmed_move = True, None

    def confirm_move(self, game, record):
        """Bắt buộc người chơi xác nhận sau khi nước robot đã khóa và thực hiện."""
        if not self.confirming:
            self.begin_confirmation()
        buttons, container, events, poll = [], None, None, None
        try:
            while self.confirmed_move is None:
                if self.action == 'quit':
                    raise KeyboardInterrupt
                game.last_frame = game.snapshot_frame.copy()
                game._show('Bam 1:R / 2:P / 3:S de xac nhan',
                           record['model_human_move'], record['robot_move'], force=True)
                if self.backend == 'notebook' and container is None:
                    import ipywidgets as widgets
                    from IPython.display import display
                    from jupyter_ui_poll import ui_events
                    if self.config.show_confirmation_buttons:
                        for number, move in enumerate(MOVES, 1):
                            button = widgets.Button(description=f'{number}: {move.upper()}', button_style='info')
                            button.on_click(lambda _, selected=move: setattr(self, 'confirmed_move', selected))
                            buttons.append(button)
                    else:
                        entry = widgets.Text(description='Nhập 1/2/3:')
                        def confirm_entry(change):
                            value = change['new'].strip()
                            if value in ('1','2','3'):
                                self.confirmed_move = MOVES[int(value)-1]
                        entry.observe(confirm_entry, names='value')
                        buttons.append(entry)
                    container = widgets.HBox(buttons)
                    display(container)
                    events = ui_events()
                    poll = events.__enter__()
                if poll is not None:
                    poll(10)
                time.sleep(.02)
            return self.confirmed_move
        finally:
            self.confirming = False
            if events is not None and poll is not None:
                events.__exit__(None, None, None)
            for button in buttons:
                button.close()
            if container is not None:
                container.close()

    def wait_action(self, game, record, finished=False):
        """Màn hình chờ trong cùng cửa sổ; không tải lại tài nguyên."""
        self.clicked, self.action = False, None
        self.button_text = ''
        self.enter_prompt = 'ENTER: NGUOI CHOI MOI' if finished else 'ENTER: BAT DAU' if not game.history else 'ENTER: VAN TIEP THEO'
        widgets_created, events, poll = [], None, None
        try:
            while not self.clicked and self.action is None:
                if game.snapshot_frame is None:
                    game.last_frame, _, _ = game.camera.get_frame()
                game._show('Reset de bat dau voi nguoi choi moi' if finished else 'San sang - nhan nut de choi',
                           record.get('human_move', UNKNOWN), record.get('robot_move','LOCKED'),
                           record.get('result',''), force=True)
                if self.backend == 'notebook' and not widgets_created:
                    import ipywidgets as widgets
                    from IPython.display import display
                    from jupyter_ui_poll import ui_events
                    for label, action in (('Enter / Tiếp tục','start'),('Reset game','reset'),('Thoát','quit')):
                        button=widgets.Button(description=label)
                        button.on_click(lambda _, selected=action: setattr(self,'action',selected))
                        widgets_created.append(button)
                    box=widgets.HBox(widgets_created)
                    display(box)
                    widgets_created.append(box)
                    events=ui_events();poll=events.__enter__()
                if poll is not None:
                    poll(10)
                time.sleep(.02)
            return self.action or ('reset' if finished else 'start')
        finally:
            self.button_text=''
            self.enter_prompt=''
            if events is not None and poll is not None:
                events.__exit__(None,None,None)
            for widget in widgets_created:
                widget.close()

    def wait_continue(self, game, record, final=False):
        """Nút chuột trong OpenCV; widget ở notebook nếu không mở được cửa sổ."""
        self.button_text = 'KET THUC' if final else 'TIEP TUC  >'
        self.clicked = False
        widget = None
        try:
            while not self.clicked:
                if game.snapshot_frame is None:
                    game.last_frame, _, _ = game.camera.get_frame()
                else:
                    game.last_frame = game.snapshot_frame.copy()
                game._show('Tran dau ket thuc' if final else 'Nhan nut de choi van tiep',
                           record.get('human_move', UNKNOWN), record.get('robot_move') or UNKNOWN,
                           record.get('result', ''), force=True)
                if self.backend == 'notebook' and widget is None:
                    import ipywidgets as widgets
                    from IPython.display import display
                    widget = widgets.Button(description='Kết thúc' if final else 'Tiếp tục',
                                            button_style='success')
                    widget.on_click(lambda _: setattr(self, 'clicked', True))
                    display(widget)
                    # Cho phép kernel nhận sự kiện widget khi cell đang chạy.
                    from jupyter_ui_poll import ui_events
                    widget._rps_events = ui_events()
                    widget._rps_poll = widget._rps_events.__enter__()
                if widget is not None:
                    widget._rps_poll(10)
                time.sleep(.03)
        finally:
            self.button_text = ''
            if widget is not None:
                if hasattr(widget, '_rps_events'):
                    widget._rps_events.__exit__(None, None, None)
                widget.close()

    def close_window(self):
        if self.window_open:
            import cv2
            try:
                cv2.destroyWindow(self.window_name)
                cv2.waitKey(1)
            except cv2.error:
                pass
            self.window_open = False

    def close(self):
        if not self.match_active:
            self.close_window()


def preview_camera(camera, detector, display, seconds):
    """Preview có giới hạn thời gian, trả về các tư thế đã xác nhận."""
    detector.reset()
    observed = set()
    deadline = time.monotonic() + seconds
    seq = -1
    try:
        while time.monotonic() < deadline:
            frame, _, seq = camera.get_frame(after_sequence=seq)
            obs = detector.process(frame)
            if obs.move in MOVES:
                observed.add(obs.move)
            display.show(frame, 'PREVIEW', obs, human=obs.move,
                         extra=f'{max(0, deadline-time.monotonic()):.0f}s con lai')
    except KeyboardInterrupt:
        print('Đã dừng preview; camera được giữ cho phiên game.')
    finally:
        detector.reset()
        display.close()
    print('Preview kết thúc. Cử chỉ đã xác nhận:', sorted(observed))
    return observed


@dataclass(frozen=True)
class LockedDecision:
    predicted_human_move: str
    robot_move: str
    latency_ms: float
    probabilities: dict
    robot_probabilities: dict = field(default_factory=dict)


class LayaDecisionEngine:
    """Đầu vào duy nhất là lịch sử hợp lệ; không nhận frame/nước của round hiện tại."""
    def __init__(self, agent, config=None, rng=None):
        self.agent, self.closed = agent, False
        self.config = (config or GameConfig()).validate()
        self.rng = rng if rng is not None else random.Random()

    def choose_move(self, history):
        if self.closed:
            raise RuntimeError('Laya đã đóng. Chạy lại Cell 6 và Cell 8.')
        recent = [{'human': r['human_move'], 'robot': r['robot_move']} for r in history[-5:]]
        state = {'task': 'Predict the next human Rock Paper Scissors move from previous rounds only.',
                 'previous_rounds': recent,
                 'human_move_counts': dict(Counter(r['human_move'] for r in history)),
                 'current_human_move': 'unknown; the round has not started'}
        questions = {'prediction': {'type': 'choice',
            'instructions': 'Which move will the human play NEXT? Use previous rounds only. '
                            'There is no observation of the current round.',
            'criteria': {'rock': 'The human will play rock.', 'paper': 'The human will play paper.',
                         'scissors': 'The human will play scissors.'}}}
        started = time.perf_counter()
        answer = self.agent.predict(state, questions)['answers']['prediction']
        elapsed = (time.perf_counter()-started)*1000
        predicted = answer.get('choice')
        probabilities = answer.get('probabilities', {})
        if predicted not in MOVES or set(probabilities) != set(MOVES) or not all(
            isinstance(p, (int, float)) and math.isfinite(p) and 0 <= p <= 1
            for p in probabilities.values()
        ) or abs(sum(probabilities.values())-1) > .01:
            raise RuntimeError('Laya trả quyết định không hợp lệ; không gửi lệnh robot.')
        if probabilities[predicted] < max(probabilities.values()) - .0002:
            raise RuntimeError('Choice Laya không khớp xác suất; không gửi lệnh robot.')
        # Đổi phân bố dự đoán sang phân bố nước khắc chế, trộn khám phá đều.
        # Giữ nguyên dự đoán top-1 để metric prediction accuracy không bị đổi nghĩa.
        exploration = self.config.laya_exploration
        total = sum(probabilities.values())
        robot_probabilities = {COUNTER_MOVE[human]:
            (1-exploration)*probabilities[human]/total + exploration/3 for human in MOVES}
        robot_move = self.rng.choices(MOVES, weights=[robot_probabilities[m] for m in MOVES], k=1)[0]
        return LockedDecision(predicted, robot_move, elapsed, dict(probabilities), robot_probabilities)

    def close(self):
        if not self.closed:
            self.closed = True
            if hasattr(self.agent, '__exit__'):
                self.agent.__exit__(None, None, None)
            self.agent = None


class _AbortableController:
    """Kiểm tra dừng trước thao tác serial; luôn cho phép lệnh nhả torque."""
    def __init__(self, controller, abort_event):
        self.controller, self.abort_event = controller, abort_event

    def __getattr__(self, name):
        value = getattr(self.controller, name)
        if not callable(value):
            return value
        def call(*args, **kwargs):
            release = name == 'write_torque_enable' and len(args) >= 2 and args[1] == 0
            if self.abort_event.is_set() and not release:
                raise RuntimeError('Đã yêu cầu dừng chuyển động.')
            return value(*args, **kwargs)
        return call


class AmazingHandRobotAdapter:
    """Tái sử dụng toàn bộ kiểm tra/trajectory hiện có qua một kết nối serial."""
    def __init__(self, config):
        self.config = config
        self.connection = None
        self.hand = None
        self.abort_event = threading.Event()
        self.lock = threading.RLock()
        self.closed = True

    def connect(self):
        if not self.closed:
            return self
        if not self.config.robot_enabled:
            self.abort_event.clear()
            self.hand = None
            self.closed = False
            print('PASS — robot_enabled=False: không mở serial, không gửi lệnh motor.')
            return self
        from rustypot import Scs0009PyController
        from AmazingHand_Notebook import NotebookHand
        adapter = self
        class SessionHand(NotebookHand):
            @contextmanager
            def _connection(self):
                with adapter.lock:
                    yield _AbortableController(adapter.connection, adapter.abort_event)
        hand = SessionHand(port=self.config.port, open_extensions=self.config.open_extensions,
                           close_flexions=self.config.close_flexions, speed_deg_s=self.config.speed_deg_s,
                           end_tolerance=self.config.end_tolerance, motion_profile=self.config.motion_profile,
                           allow_voltage_warning=self.config.allow_voltage_warning, spread=0)
        self.connection = Scs0009PyController(serial_port=self.config.port, baudrate=1_000_000, timeout=.2)
        self.hand = hand
        self.abort_event.clear()
        try:
            hand.inspect()  # Chỉ đọc; chưa đổi tư thế hoặc bật torque.
            self.closed = False
        except BaseException:
            self.connection.close()
            self.connection = None
            raise
        print(f'PASS — AmazingHand {self.config.port}: một kết nối cho cả phiên; chưa chuyển động.')
        return self

    def execute_move(self, move):
        if move not in MOVES or self.closed:
            raise RuntimeError('Robot chưa sẵn sàng hoặc nước đi không hợp lệ.')
        if self.abort_event.is_set():
            raise RuntimeError('Robot đang ở trạng thái dừng; chạy lại Cell 8.')
        started = time.perf_counter()
        if self.config.robot_enabled:
            from AmazingHand_LayaRPS import perform_move
            perform_move(self.hand, move)
        # run_cycles chỉ trả về sau CONFIRMED và HOLD_CONFIRMED.
        return {'confirmed': True, 'simulated': not self.config.robot_enabled,
                'latency_ms': (time.perf_counter()-started)*1000}

    def cancel(self):
        self.abort_event.set()

    def emergency_release(self):
        if self.hand is not None:
            if not self.lock.acquire(timeout=3):
                raise RuntimeError('Motor chưa dừng; không gửi thêm lệnh song song. Dừng phiên và kiểm tra nguồn.')
            try:
                self.abort_event.clear()
                self.hand.release()
            finally:
                self.abort_event.set()
                self.lock.release()

    def reset_pose(self):
        if self.closed:
            raise RuntimeError('Robot đã đóng.')
        if self.config.robot_enabled:
            self.execute_move(self.config.reset_move)
            self.hand.release()

    def close(self):
        if self.closed:
            return
        self.cancel()
        if not self.lock.acquire(timeout=3):
            raise RuntimeError('Motor chưa nhả quyền dùng serial; không đóng cổng giữa một thao tác đang chạy.')
        try:
            self.emergency_release()
        finally:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
            self.closed = True
            self.hand = None
            self.lock.release()


def summarize_records(records):
    """Tách mẫu số nhận diện và mẫu số ván hợp lệ; không tính lỗi như thua."""
    import numpy as np
    valid = [r for r in records if r.get('valid')]
    samples = [r['laya_latency_ms'] for r in records if r.get('laya_latency_ms') is not None]
    gesture_samples = [r['gesture_inference_ms'] for r in records if r.get('gesture_inference_ms') is not None]
    denominator = len(valid)
    def rate(count, n):
        return count/n if n else None
    return {
        'rounds': len(records), 'valid_rounds': denominator,
        'gesture_recognition_success_rate': rate(sum(r.get('model_human_move', r.get('human_move')) in MOVES for r in records), len(records)),
        'robot_win_rate': rate(sum(r['result'] == 'ROBOT_WIN' for r in valid), denominator),
        'robot_loss_rate': rate(sum(r['result'] == 'HUMAN_WIN' for r in valid), denominator),
        'draw_rate': rate(sum(r['result'] == 'DRAW' for r in valid), denominator),
        'laya_prediction_accuracy': rate(sum(r['human_move'] == r['predicted_human_move'] for r in valid), denominator),
        'laya_latency_mean_ms': float(np.mean(samples)) if samples else None,
        'laya_latency_p95_ms': float(np.percentile(samples, 95)) if samples else None,
        'gesture_latency_mean_ms': float(np.mean(gesture_samples)) if gesture_samples else None,
        'gesture_latency_p95_ms': float(np.percentile(gesture_samples, 95)) if gesture_samples else None,
    }


class RPSGame:
    """Một lần gọi = một round; tài nguyên và history thuộc phiên, không thuộc round."""
    def __init__(self, config, camera, detector, decision_engine, robot_controller, display, log_path):
        self.config = config.validate()
        self.camera, self.detector = camera, detector
        self.decision_engine, self.robot_controller = decision_engine, robot_controller
        self.display = display
        self.log_path = Path(log_path)
        self.history, self.records = [], []
        self.scoreboard = {'human': 0, 'robot': 0, 'draw': 0}
        self.state = 'READY'
        self.state_trace = ['READY']
        self.closed = False
        self.busy = False
        self.round_number = 0
        self.session_id = uuid.uuid4().hex[:12]
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='AmazingHand-motor')
        self.motor_future = None
        self.last_frame = None
        self.snapshot_frame = None
        self.last_observation = None
        self.locked_decision = None

    def _transition(self, state):
        self.state = state
        self.state_trace.append(state)

    def _show(self, text='', human=UNKNOWN, robot='LOCKED', result='', force=False):
        if self.last_frame is not None:
            self.display.show(self.last_frame, self.state, self.last_observation,
                              human=human, robot=robot, result=result, scores=self.scoreboard,
                              extra=text, force=force)

    def _wait_motor(self, future, deadline, human=UNKNOWN, robot='LOCKED'):
        while not future.done():
            if time.monotonic() > deadline:
                self.robot_controller.cancel()
                raise TimeoutError('Quá thời gian xác nhận chuyển động robot.')
            if self.snapshot_frame is None:
                self.last_frame, _, _ = self.camera.get_frame()
            else:
                self.last_frame = self.snapshot_frame.copy()
            self._show('Cho robot xac nhan hoan tat', human=human, robot=robot)
            time.sleep(.015)
        result = future.result()
        if not result or not result.get('confirmed'):
            raise RuntimeError('Robot không xác nhận hoàn tất tư thế.')
        return result

    def _stop_motor(self):
        self.closed = True
        self.robot_controller.cancel()
        if self.motor_future is not None and not self.motor_future.done():
            try:
                self.motor_future.result(timeout=3)
            except FutureTimeout:
                self.closed = True
                print('Motor chưa dừng. Phiên đã khóa; không chạy round tiếp theo.')
                return
            except BaseException:
                pass
        self.robot_controller.emergency_release()
        print('Round đã dừng an toàn. Chạy Cell 8 để mở lại phiên; không phải tải lại model.')

    def play_round(self):
        if self.closed:
            print('Phiên chưa sẵn sàng hoặc đã đóng. Chạy Cell 8 trước.')
            return None
        if self.busy:
            raise RuntimeError('Round trước chưa kết thúc.')
        self.busy = True
        self.round_number += 1
        self.state_trace = ['READY']
        self.state = 'READY'
        self.last_observation = None
        self.snapshot_frame = None
        self.detector.reset()
        self.display.start_round()
        started = time.perf_counter()
        record = {'session_id': self.session_id, 'round_id': self.round_number,
                  'timestamp': datetime.now(timezone.utc).isoformat(), 'human_move': UNKNOWN,
                  'predicted_human_move': None, 'robot_move': None, 'gesture_confidence': 0,
                  'result': 'INVALID_ROUND', 'valid': False, 'status': 'pending',
                  'laya_latency_ms': None, 'gesture_latency_ms': None,
                  'gesture_inference_ms': None, 'motor_latency_ms': None,
                  'robot_confirmed': False, 'total_round_ms': None,
                  'simulated_robot': not self.config.robot_enabled, 'error': None}
        interrupted = False
        try:
            if self.camera.closed or self.decision_engine.closed or self.robot_controller.closed:
                raise RuntimeError('Camera/Laya/robot đã đóng. Chạy lại Cell 8.')
            self.last_frame, _, sequence = self.camera.get_frame()
            # Chưa gọi nhận diện cử chỉ. Quyết định chỉ nhận bản sao history cũ.
            self._transition('COUNTDOWN')
            countdown_end = time.monotonic() + self.config.countdown_seconds
            decision_future = self.pool.submit(self.decision_engine.choose_move,
                                              tuple(dict(r) for r in self.history))
            while not decision_future.done():
                self.last_frame, _, sequence = self.camera.get_frame(after_sequence=sequence)
                self._show(str(max(1, math.ceil(countdown_end-time.monotonic()))))
                if time.monotonic() > countdown_end + self.config.motor_timeout_seconds:
                    raise TimeoutError('Laya quá thời gian đưa ra quyết định.')
            self.locked_decision = decision_future.result()
            decision = self.locked_decision
            record.update(predicted_human_move=decision.predicted_human_move,
                          robot_move=decision.robot_move, laya_latency_ms=decision.latency_ms,
                          laya_probabilities=dict(decision.probabilities),
                          robot_probabilities=dict(decision.robot_probabilities),
                          decision_policy='probability_sampling_with_exploration',
                          laya_exploration=self.config.laya_exploration)
            print(f'[ROUND {self.round_number}] Laya: {decision.robot_move.upper()} ({decision.latency_ms:.1f} ms).')
            while time.monotonic() < countdown_end:
                self.last_frame, _, sequence = self.camera.get_frame(after_sequence=sequence)
                self._show(str(max(1, math.ceil(countdown_end-time.monotonic()))))
            self._transition('COMMIT')
            self._show('Da khoa nuoc robot', force=True)
            self._transition('REVEAL')
            self.detector.reset()
            if self.config.require_confirmation:
                self.display.begin_confirmation()
            self._show('RA TAY!', robot=decision.robot_move, force=True)
            revealed = time.monotonic()
            self.motor_future = self.pool.submit(self.robot_controller.execute_move, decision.robot_move)
            motor_deadline = revealed + self.config.motor_timeout_seconds
            capture_at = revealed + self.config.snapshot_delay_seconds
            while time.monotonic() < capture_at:
                self.last_frame, _, sequence = self.camera.get_frame(after_sequence=sequence)
                self._show('RA TAY! Chuan bi chup', robot=decision.robot_move)
                if self.motor_future.done():
                    self.motor_future.result()
            # Chụp đúng một frame mới sau RA TAY + độ trễ thao tác người chơi.
            self.last_frame, captured, sequence = self.camera.get_frame(
                timeout=self.config.camera_timeout_seconds,
                after_sequence=sequence, min_time=capture_at)
            self.snapshot_frame = self.last_frame.copy()
            record.update(recognition_mode='single_snapshot', snapshot_sequence=sequence,
                          snapshot_after_reveal_ms=(captured-revealed)*1000)
            import cv2
            snapshot_path = self.log_path.parent / 'snapshots' / self.session_id / f'{self.round_number:03d}.jpg'
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(snapshot_path), self.snapshot_frame):
                raise RuntimeError('Không lưu được ảnh đã chụp; ván không được tính điểm.')
            record['snapshot_path'] = str(snapshot_path.resolve())
            self._show('DA CHUP - Dang phan loai anh', robot=decision.robot_move, force=True)
            # Chỉ một lần H5 inference. Không lặp lại cùng ảnh để tạo đồng thuận giả.
            self.last_observation = self.detector.process(self.snapshot_frame, single_frame=True)
            obs = self.last_observation
            record.update(human_move=obs.move, gesture_confidence=obs.confidence,
                          gesture_latency_ms=(time.monotonic()-revealed)*1000,
                          gesture_inference_ms=obs.latency_ms,
                          gesture_diagnostics={'frames': 1, 'labels': {obs.label: 1},
                                               'reasons': {obs.reason or 'Da xac nhan': 1},
                                               'best_confidence': obs.confidence,
                                               'probabilities': obs.probabilities,
                                               'roi': list(self.config.roi)})
            print(f'[SNAPSHOT] Đã chụp 1 ảnh: {snapshot_path}; '
                  f'H5: {obs.move}, confidence={obs.confidence:.1%}', flush=True)
            if obs.move == UNKNOWN:
                print('[GESTURE]', obs.reason, json.dumps(obs.probabilities), flush=True)
            motor = self._wait_motor(self.motor_future, motor_deadline,
                                     record['human_move'], decision.robot_move)
            record.update(robot_confirmed=True, motor_latency_ms=motor['latency_ms'])
            self._transition('VALIDATE')
            record.update(model_human_move=record['human_move'], human_move_source='model',
                          human_confirmed=False, model_overridden=False)
            if self.config.require_confirmation:
                confirmed = self.display.confirm_move(self, record)
                if confirmed not in MOVES:
                    raise RuntimeError('Nước người chơi xác nhận không hợp lệ.')
                record.update(human_move=confirmed, human_move_source='human_confirmation',
                              human_confirmed=True, model_overridden=confirmed != record['model_human_move'])
                print(f'[XÁC NHẬN] Model: {record["model_human_move"]} → Bạn chọn: {confirmed}', flush=True)
            if record['human_move'] in MOVES:
                human = record['human_move']
                result = 'DRAW' if human == decision.robot_move else 'ROBOT_WIN' if COUNTER_MOVE[human] == decision.robot_move else 'HUMAN_WIN'
                record.update(result=result, status='valid')
            else:
                record['status'] = 'snapshot_unknown'
            self._transition('RESULT')
            show_until = time.monotonic() + self.config.result_seconds
            self._show('WIN/LOSE theo goc nhin nguoi choi: ' +
                       {'HUMAN_WIN': 'WIN', 'ROBOT_WIN': 'LOSE', 'DRAW': 'DRAW'}.get(record['result'], 'INVALID_ROUND'),
                       record['human_move'], decision.robot_move, record['result'], force=True)
            while time.monotonic() < show_until:
                self.last_frame = self.snapshot_frame.copy()
                time.sleep(.015)
                self._show(human=record['human_move'], robot=decision.robot_move, result=record['result'])
            self._transition('RESET')
            self.motor_future = self.pool.submit(self._reset_robot)
            self._wait_motor(self.motor_future, time.monotonic()+self.config.motor_timeout_seconds,
                             record['human_move'], decision.robot_move)
            record['valid'] = record['status'] == 'valid'
        except KeyboardInterrupt:
            interrupted = True
            print('Đã dừng round. Không ghi kết quả, không cộng điểm và không cập nhật history.')
            try:
                self._stop_motor()
            except Exception as stop_error:
                self.closed = True
                print('Lỗi khi dừng robot:', stop_error)
        except Exception as exc:
            record.update(valid=False, result='INVALID_ROUND', status='error',
                          error=f'{type(exc).__name__}: {exc}')
            print('INVALID_ROUND —', record['error'])
            try:
                self._stop_motor()
            except Exception as stop_error:
                self.closed = True
                record['error'] += f'; lỗi nhả torque: {stop_error}'
        finally:
            self.detector.reset()
            self.display.confirming = False
            self.display.close()
            self.busy = False
            self.state = 'READY' if not self.closed else 'CLOSED'
        if interrupted:
            return None
        record['total_round_ms'] = (time.perf_counter()-started)*1000
        record['state_trace'] = list(self.state_trace)
        # Ghi log thành công trước khi commit history/điểm để tránh ván nửa chừng.
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(record, ensure_ascii=False) + '\n')
        self.records.append(record)
        if record['valid']:
            self.history.append(dict(record))
            self.scoreboard[{'HUMAN_WIN': 'human', 'ROBOT_WIN': 'robot', 'DRAW': 'draw'}[record['result']]] += 1
        self._show(human=record['human_move'], robot=record['robot_move'] or 'UNKNOWN', result=record['result'], force=True)
        self.display.close()
        print(f"[KẾT QUẢ] Bạn: {record['human_move']} | Robot: {record['robot_move']} | {record['result']}")
        print('[TỶ SỐ]', self.scoreboard)
        print('[METRICS]', json.dumps(self.metrics(), ensure_ascii=False))
        return record

    def play_match(self):
        """Mỗi lần chạy cell cuối mở trận mới; người đạt 3 điểm trước thắng."""
        if self.closed or self.busy:
            print('Chạy Cell 8 để mở lại phiên trước.')
            return
        self.history.clear()
        self.records.clear()
        self.scoreboard = {'human': 0, 'robot': 0, 'draw': 0}
        self.round_number = 0
        self.session_id = uuid.uuid4().hex[:12]
        self.display.match_active = True
        self.display.start_round()
        try:
            while max(self.scoreboard['human'], self.scoreboard['robot']) < self.config.target_wins:
                self.display.match_index = self.round_number+1
                record = self.play_round()
                if record is None or self.closed:
                    return
                final = max(self.scoreboard['human'], self.scoreboard['robot']) >= self.config.target_wins
                if final:
                    human, robot = self.scoreboard['human'], self.scoreboard['robot']
                    outcome = 'BAN THANG TRAN' if human > robot else 'ROBOT THANG TRAN' if robot > human else 'HOA TRAN'
                    print(outcome, self.scoreboard)
                    record = dict(record, result=outcome)
                self.display.wait_continue(self, record, final=final)
        except KeyboardInterrupt:
            print('Đã đóng trận. Chạy lại cell cuối để bắt đầu với người chơi mới.')
        finally:
            self.display.match_active = False
            self.display.close()

    def reset_match(self):
        """Reset dữ liệu người chơi, giữ nguyên model, camera và serial."""
        if self.busy:
            raise RuntimeError('Chờ ván hiện tại hoàn tất trước khi reset.')
        self.history.clear()
        self.records.clear()
        self.scoreboard = {'human':0, 'robot':0, 'draw':0}
        self.round_number = 0
        self.session_id = uuid.uuid4().hex[:12]
        self.snapshot_frame = self.last_observation = None
        self.state = 'READY'
        self.display.match_index = 1

    def run_app(self):
        """Cell cuối chỉ mở game; các nút quản lý nhiều người chơi trong một phiên."""
        if self.closed or self.busy:
            print('Chạy Cell 8 để mở lại phiên trước.')
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        ui_log = self.log_path.parent / 'rps_ui_session.log'
        with ui_log.open('a', encoding='utf-8', buffering=1) as output, redirect_stdout(output), redirect_stderr(output):
            self.display.app_active = self.display.match_active = True
            self.display.handle = None
            self.display.start_round()
            self.reset_match()
            record = {}
            finished = False
            try:
                self._prepare_ready_pose()
                while not self.closed:
                    action = self.display.wait_action(self, record, finished)
                    if action == 'quit':
                        break
                    if action == 'reset' or finished:
                        self.reset_match()
                        self._prepare_ready_pose()
                        record, finished = {}, False
                        continue
                    self.display.match_index = self.round_number+1
                    record = self.play_round()
                    if record is None or self.closed:
                        break
                    finished = max(self.scoreboard['human'],self.scoreboard['robot']) >= self.config.target_wins
                    self.state = 'MATCH_OVER' if finished else 'RESULT'
                    if finished:
                        winner = 'BAN THANG TRAN' if self.scoreboard['human'] >= self.config.target_wins else 'ROBOT THANG TRAN'
                        record = dict(record, result=winner)
            except KeyboardInterrupt:
                # play_round tự dừng motor nếu interrupt xuất hiện trong ván.
                print('Đã thoát giao diện game.')
                if self.motor_future is not None and not self.motor_future.done():
                    self._stop_motor()
            except Exception as exc:
                print('Lỗi tư thế chờ/giao diện:', exc)
                self._stop_motor()
            finally:
                self.display.app_active = self.display.match_active = False
                self.display.button_text = ''
                self.display.enter_prompt = ''
                self.display.action = None
                self.display.close()
        if self.closed:
            print(f'Phiên đã dừng do lỗi hoặc interrupt trong ván. Xem {ui_log}; chạy Cell 8 để mở lại.')

    def _prepare_ready_pose(self):
        self.state = 'RESET'
        self.motor_future = self.pool.submit(self._reset_robot)
        self._wait_motor(self.motor_future, time.monotonic()+self.config.motor_timeout_seconds)
        self.state = 'READY'

    def _reset_robot(self):
        self.robot_controller.reset_pose()
        return {'confirmed': True}

    def metrics(self):
        return summarize_records(self.records)

    def close(self, keep_models=False):
        if self.busy:
            self.robot_controller.cancel()
        errors = []
        for resource in (self.robot_controller, self.camera, self.display):
            try:
                resource.close()
            except Exception as exc:
                errors.append(str(exc))
        self.pool.shutdown(wait=False, cancel_futures=True)
        if not keep_models:
            for resource in (self.detector.session, self.decision_engine):
                try:
                    resource.close()
                except Exception as exc:
                    errors.append(str(exc))
        self.closed = True
        if errors:
            print('Lỗi khi đóng phiên:', '; '.join(errors))


class GameNotReady:
    """Cell cuối vẫn chỉ cần game.play_round() trước khi khởi tạo phiên."""
    def play_round(self):
        print('Chạy Cell 8 để khởi tạo game trước.')

    def play_match(self):
        self.play_round()

    def run_app(self):
        self.play_round()

    def close(self, **kwargs):
        pass
