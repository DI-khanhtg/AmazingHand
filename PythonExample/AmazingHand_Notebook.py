"""Cell-friendly gestures; each operation owns and closes its serial connection."""

from contextlib import contextmanager
import math

from rustypot import Scs0009PyController
from AmazingHand_HardwareDemo import (
    SerialFeedbackError, default_middle_positions, move_pose, read_one, read_servo, validate_movement_servo,
)
from AmazingHand_GripCycles import run_cycles
from AmazingHand_VSign import v_targets


class NotebookHand:
    FINGERS = ('index', 'middle', 'ring', 'thumb')

    def __init__(self, port='COM3', open_extensions=(67, 58, 37, 35),
                 side='right', spread=15, allow_voltage_warning=True, dry_run=False,
                 speed_deg_s=40, close_flexions=(92, 90, 90, 90), end_tolerance=4,
                 motion_profile='smooth'):
        if not math.isfinite(speed_deg_s) or speed_deg_s <= 0:
            raise ValueError('Speed must be a finite positive number of degrees per second.')
        if len(open_extensions) != 4 or not all(math.isfinite(x) and 35 <= x <= 70 for x in open_extensions):
            raise ValueError('Specify four opening angles in the range 35-70 degrees.')
        if len(close_flexions) != 4 or not all(math.isfinite(x) and 0 < x <= 100 for x in close_flexions):
            raise ValueError('Specify four closing angles in the range 0-100 degrees (excluding zero).')
        if end_tolerance not in (3, 4, 5):
            raise ValueError('Endpoint tolerance must be 3, 4 or 5 degrees.')
        if motion_profile not in ('linear', 'smooth'):
            raise ValueError('Motion profile must be linear or smooth.')
        v_targets(side, open_extensions[0], spread)
        self.port = port
        self.open_extensions = tuple(open_extensions)
        self.close_flexions = tuple(close_flexions)
        self.side = side
        self.spread = spread
        self.allow_voltage_warning = allow_voltage_warning
        self.dry_run = dry_run
        self.speed_deg_s = speed_deg_s
        self.end_tolerance = end_tolerance
        self.motion_profile = motion_profile

    @contextmanager
    def _connection(self):
        controller = Scs0009PyController(serial_port=self.port, baudrate=1_000_000, timeout=.2)
        try:
            yield controller
        finally:
            controller.close()

    def inspect(self):
        """Read and validate all eight servos without movement/torque writes."""
        result = []
        with self._connection() as controller:
            for servo_id in range(1, 9):
                try:
                    row = read_servo(controller, servo_id)
                except SerialFeedbackError as exc:
                    raise RuntimeError(
                        f'{self.port}: servo ID {servo_id} trả dữ liệu không hợp lệ sau 3 lần đọc. '
                        'Rút USB và nguồn bàn tay, cắm lại nguồn rồi USB, '
                        'sau đó chạy lại cell khởi tạo. Chưa gửi lệnh chuyển động.'
                    ) from exc
                validate_movement_servo(row, self.allow_voltage_warning)
                result.append(self._feedback(controller, row))
        return result

    @staticmethod
    def _feedback(controller, row):
        goal = read_one(controller, 'goal_position', row['id'])
        return dict(id=row['id'], position_deg=round(math.degrees(row['position']), 2),
                    goal_deg=round(math.degrees(goal), 2),
                    error_deg=round(math.degrees(row['position']-goal), 2),
                    load=controller.read_register(row['id'], 'present_load'),
                    voltage_V=row['voltage']/10, temperature_C=row['temperature'],
                    torque=row['torque'], status=row['status'])

    def targets(self, raised=()):
        raised = set(raised)
        if not raised.issubset(self.FINGERS):
            raise ValueError(f'Choose from {self.FINGERS}.')
        offsets = default_middle_positions()
        angles = []
        for finger, name in enumerate(self.FINGERS):
            angle = -self.open_extensions[finger] if name in raised else self.close_flexions[finger]
            angles.extend((offsets[2*finger] + angle, offsets[2*finger+1] - angle))
        return angles

    def _hold(self, angles, label):
        with self._connection() as controller:
            run_cycles(controller, count=1, dry_run=self.dry_run,
                       allow_voltage_warning=self.allow_voltage_warning, end_tolerance=self.end_tolerance,
                       custom_target_degrees=angles, pose_label=label,
                       speed_deg_s=self.speed_deg_s, motion_profile=self.motion_profile)

    def open_all(self):
        self._hold(self.targets(self.FINGERS), 'OPEN_ALL')

    def close_all(self):
        self._hold(self.targets(), 'CLOSE_ALL')

    def v_sign(self):
        angles = v_targets(self.side, self.open_extensions[0], self.spread)
        delta = self.open_extensions[1] - self.open_extensions[0]
        angles[2] -= delta
        angles[3] += delta
        folded = self.targets()
        angles[4:] = folded[4:]
        self._hold(angles, 'V_SIGN')

    def raise_finger(self, name):
        if name not in self.FINGERS:
            raise ValueError(f'Choose from {self.FINGERS}.')
        self._hold(self.targets((name,)), f'RAISE_{name.upper()}')

    def _move_single(self, name, pose, value):
        if name not in self.FINGERS or pose not in ('open', 'close'):
            raise ValueError('Choose a valid finger and pose open/close.')
        finger = self.FINGERS.index(name) + 1
        ids = (2*finger-1, 2*finger)
        offsets = default_middle_positions()
        angle = -value if pose == 'open' else value
        with self._connection() as controller:
            rows = {i: read_servo(controller, i) for i in ids}
            for i, row in rows.items():
                validate_movement_servo(row, self.allow_voltage_warning)
                target = math.radians(offsets[i-1] + (angle if i % 2 else -angle))
                if not row['min_angle'] <= target <= row['max_angle']:
                    raise RuntimeError(f'ID {i}: target exceeds configured angle limits.')
            if self.dry_run:
                print(f'DRY_RUN: {name} {pose} target checked; no commands sent.')
                return []
            move_pose(controller, rows, offsets, (finger,), angle, pose, speed=4,
                      allow_voltage_warning=self.allow_voltage_warning, end_tolerance=self.end_tolerance)
            return [self._feedback(controller, read_servo(controller, i)) for i in ids]

    def test_finger(self, name, pose):
        """Slowly test one configured endpoint; other fingers receive no writes."""
        if name not in self.FINGERS or pose not in ('open', 'close'):
            raise ValueError('Choose a valid finger and pose open/close.')
        profile = self.open_extensions if pose == 'open' else self.close_flexions
        return self._move_single(name, pose, profile[self.FINGERS.index(name)])

    def adjust_endpoint(self, name, pose, delta=1):
        """One bounded adjustment; commit in memory only after successful feedback."""
        if name not in self.FINGERS or pose not in ('open', 'close'):
            raise ValueError('Choose a valid finger and pose open/close.')
        if not math.isfinite(delta) or not 0 < abs(delta) <= 2:
            raise ValueError('Adjust by a nonzero step of at most two degrees.')
        index = self.FINGERS.index(name)
        profile = list(self.open_extensions if pose == 'open' else self.close_flexions)
        profile[index] += delta
        if (pose == 'open' and not 35 <= profile[index] <= 70) or (pose == 'close' and not 0 < profile[index] <= 100):
            raise ValueError('Requested endpoint is outside the adjustment range.')
        feedback = self._move_single(name, pose, profile[index])
        if not self.dry_run:
            if pose == 'open':
                self.open_extensions = tuple(profile)
            else:
                self.close_flexions = tuple(profile)
            print('Servo target reached. Visually check finger joints; profile updated in memory only.')
        return feedback

    def release(self):
        """Attempt every ID even if one servo fails; then verify torque is off."""
        if self.dry_run:
            print('DRY_RUN: no torque commands sent.')
            return
        errors = []
        with self._connection() as controller:
            for servo_id in range(1, 9):
                try:
                    controller.write_torque_enable(servo_id, 0)
                except Exception as exc:
                    errors.append(f'ID {servo_id}: {exc}')
            for servo_id in range(1, 9):
                try:
                    if read_one(controller, 'torque_enable', servo_id) != 0:
                        errors.append(f'ID {servo_id}: torque remains enabled')
                except Exception as exc:
                    errors.append(f'ID {servo_id}: {exc}')
        if errors:
            raise RuntimeError('Torque release incomplete: ' + '; '.join(errors))
        print('Đã nhả torque cả 8 servo và đóng cổng kết nối.')
