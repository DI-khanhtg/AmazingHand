"""Center only SCS0009 IDs 1 and 2 for detached-horn mechanical calibration."""

import argparse
import math
import sys
import time

from rustypot import Scs0009PyController
from AmazingHand_HardwareDemo import read_one, read_servo, validate_servo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--baudrate', type=int, default=1_000_000)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='Read telemetry only; send no movement commands.')
    mode.add_argument('--horns-detached', action='store_true', help='Both index servo horns are detached from the motor shafts. Center the bare shafts to 0 degrees.')
    args = parser.parse_args()
    controller = Scs0009PyController(serial_port=args.port, baudrate=args.baudrate, timeout=.2)
    touched = []
    try:
        rows = [read_servo(controller, servo_id) for servo_id in (1, 2)]
        for row in rows:
            validate_servo(row)
            if not row['min_angle'] <= 0 <= row['max_angle']:
                raise RuntimeError(f"ID {row['id']} does not allow the zero position.")
            print(f"ID {row['id']}: {math.degrees(row['position']):.2f} deg -> 0.00 deg", flush=True)
        if args.dry_run:
            print('DRY_RUN: no movement or torque commands sent.', flush=True)
            return

        print('Centering bare index servo shafts at 5 deg/s. Keep horns detached until complete.', flush=True)
        for row in rows:
            touched.append(row['id'])
            controller.write_goal_speed(row['id'], math.radians(5))
            controller.write_goal_position(row['id'], row['position'])
            if abs(read_one(controller, 'goal_position', row['id']) - row['position']) > math.radians(.5):
                raise RuntimeError(f"ID {row['id']} did not accept its initial target.")
        for row in rows:
            controller.write_torque_enable(row['id'], 1)

        duration = max(abs(row['position']) for row in rows) / math.radians(5)
        steps = max(1, math.ceil(duration / .05))
        for step in range(1, steps + 1):
            for row in rows:
                controller.write_goal_position(row['id'], row['position'] * (1 - step / steps))
            time.sleep(.05)
            if step % 4 == 0 or step == steps:
                for row in rows:
                    actual = read_one(controller, 'present_position', row['id'])
                    goal = row['position'] * (1 - step / steps)
                    status = controller.read_register(row['id'], 'status')
                    load = abs(controller.read_register(row['id'], 'present_load'))
                    voltage = controller.read_register(row['id'], 'present_voltage')
                    temperature = controller.read_register(row['id'], 'present_temperature')
                    if status or load > 300 or temperature >= 55 or not row['min_voltage'] <= voltage <= row['max_voltage']:
                        raise RuntimeError(f"ID {row['id']} feedback check failed; stopping.")
                    if not math.isfinite(actual) or abs(actual - goal) > math.radians(8):
                        raise RuntimeError(f"ID {row['id']} did not follow the centering target.")
        time.sleep(.8)
        for row in rows:
            final = read_servo(controller, row['id'])
            validate_servo(final)
            print(f"ID {row['id']}: centered position {math.degrees(final['position']):.2f} deg", flush=True)
            if abs(final['position']) > math.radians(2):
                raise RuntimeError(f"ID {row['id']} did not center within 2 degrees.")
        print('CENTERED: index shafts are near 0 degrees. Torque is being released. Disconnect servo power before remounting horns per assembly guide page 22; do not rotate the shafts.', flush=True)
    finally:
        for servo_id in touched:
            try:
                controller.write_torque_enable(servo_id, 0)
            except Exception as exc:
                print(f'Could not release ID {servo_id}: {exc}', file=sys.stderr)
        controller.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped. Attempted to release index torque.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
