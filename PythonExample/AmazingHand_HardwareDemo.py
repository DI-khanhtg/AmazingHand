"""Inspect servo telemetry, test one finger, open the full hand, or release torque."""

import argparse
import ast
import json
import math
from pathlib import Path
import sys
import time

from rustypot import Scs0009PyController


def read_one(controller, name, servo_id):
    """Recent rustypot versions return a one-element list for typed reads."""
    value = getattr(controller, 'read_' + name)(servo_id)
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise RuntimeError(f'Unexpected feedback length for ID {servo_id}: {name}')
        return value[0]
    return value


class SerialFeedbackError(RuntimeError):
    """Repeated malformed replies, distinct from valid servo fault telemetry."""


def read_servo(controller, servo_id):
    # Retry only read-only startup telemetry, never movement commands or faults.
    for attempt in range(3):
        try:
            return _read_servo_once(controller, servo_id)
        except RuntimeError as exc:
            if str(exc).strip().lower() != 'parsing error':
                raise
            if attempt == 2:
                raise SerialFeedbackError(
                    f'ID {servo_id}: malformed serial replies on all 3 attempts. '
                    'Check servo power and USB/TTL connections before retrying.'
                ) from exc
            time.sleep(.05)


def _read_servo_once(controller, servo_id):
    # The generic register API decodes the SCS big-endian model number.
    model = controller.read_register(servo_id, 'model_number')
    if model not in Scs0009PyController.models().values():
        raise RuntimeError(f'ID {servo_id} has model number {model}, not SCS0009; refusing to interpret its registers.')
    return {
        'id': servo_id,
        'model': model,
        'position': read_one(controller, 'present_position', servo_id),
        'torque': read_one(controller, 'torque_enable', servo_id),
        'speed': read_one(controller, 'goal_speed', servo_id),
        'temperature': read_one(controller, 'present_temperature', servo_id),
        'voltage': read_one(controller, 'present_voltage', servo_id),
        'min_voltage': read_one(controller, 'min_voltage_limit', servo_id),
        'max_voltage': read_one(controller, 'max_voltage_limit', servo_id),
        'min_angle': read_one(controller, 'min_angle_limit', servo_id),
        'max_angle': read_one(controller, 'max_angle_limit', servo_id),
        'status': read_one(controller, 'status', servo_id),
    }


def validate_servo(row):
    if not math.isfinite(row['position']):
        raise RuntimeError('Invalid position feedback.')
    if row['status'] != 0 or row['temperature'] >= 55:
        raise RuntimeError(f"Servo {row['id']} reports an alarm or high temperature.")
    if not row['min_voltage'] <= row['voltage'] <= row['max_voltage']:
        raise RuntimeError(f"Servo {row['id']} voltage is outside its configured limits.")
    if row['torque'] not in (0, 1) or row['min_angle'] >= row['max_angle']:
        raise RuntimeError(f"Servo {row['id']} is not configured for ordinary position control.")


def default_middle_positions():
    # Read the user's configured offsets without importing the hardware demo.
    source = Path(__file__).with_name('AmazingHand_Demo.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'MiddlePos' for target in statement.targets):
            values = ast.literal_eval(statement.value)
            if len(values) == 8 and all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
                return values
    raise RuntimeError('Cannot read the eight MiddlePos offsets from AmazingHand_Demo.py.')


def validate_movement_servo(row, allow_voltage_warning=False):
    checked = dict(row)
    if allow_voltage_warning:
        checked['min_voltage'] = 40
        checked['max_voltage'] = min(74, checked['max_voltage'])
        checked['status'] &= ~1
    validate_servo(checked)


def open_hand(controller, rows, middle_positions, fingers=(1, 2, 3, 4), extension=35, speed=8, allow_voltage_warning=False):
    if extension == 40 and tuple(fingers) != (1,):
        raise RuntimeError('The repository 40-degree pointing target is supported only with --open-finger 1.')
    move_pose(controller, rows, middle_positions, fingers, -extension, 'open', speed, allow_voltage_warning)


def wait_for_endpoint(probe, tolerance, sleep):
    """Monitor for up to 3 s; require three consecutive endpoint samples.

    The probe must retain the moving error, load, temperature and voltage checks.
    Waiting never changes the target or the permitted final error.
    """
    consecutive = 0
    for sample in range(30):
        sleep(.1)
        feedback = probe()
        within = all(abs(row['position'] - row['goal']) <= math.radians(tolerance)
                     for row in feedback)
        consecutive = consecutive + 1 if within else 0
        if sample >= 7 and consecutive >= 3:
            return feedback
    row = max(feedback, key=lambda item: abs(item['position'] - item['goal']))
    raise RuntimeError(
        f"ID {row['id']} did not stay within {tolerance}-degree position tolerance for three samples after settling: "
        f"actual={math.degrees(row['position']):.2f}, goal={math.degrees(row['goal']):.2f}, "
        f"error={math.degrees(row['position']-row['goal']):+.2f} deg; stopping servos."
    )


def move_pose(controller, rows, middle_positions, fingers, angle, pose, speed, allow_voltage_warning=False, end_tolerance=3):
    """Move pairs gradually; angle is the odd-servo angle relative to MiddlePos."""
    if not 0 < speed <= 8 or not math.isfinite(angle):
        raise RuntimeError('Invalid bounded movement parameters.')
    if end_tolerance not in (3, 4, 5):
        raise ValueError('Endpoint tolerance must be 3, 4 or 5 degrees.')
    selected_ids = {servo_id for finger in fingers for servo_id in (2 * finger - 1, 2 * finger)}
    if not selected_ids.issubset(rows):
        raise RuntimeError('Opening requires both identified servos for every selected finger.')
    rows = {servo_id: read_servo(controller, servo_id) for servo_id in rows}
    targets = {servo_id: math.radians(middle_positions[servo_id - 1] + (angle if servo_id % 2 else -angle))
               for servo_id in selected_ids}
    for row in (rows[servo_id] for servo_id in selected_ids):
        validate_movement_servo(row, allow_voltage_warning)
        if not row['min_angle'] <= targets[row['id']] <= row['max_angle']:
            raise RuntimeError(f"Pose target is outside ID {row['id']}'s configured limits.")

    snapshot_dir = Path(__file__).resolve().parent.parent / '.tools' / 'hardware'
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f'before-{pose}-{time.time_ns()}.json'
    snapshot_path.write_text(json.dumps({'servos': rows, 'middle_positions_degrees': middle_positions,
                                         'target_degrees': {key: math.degrees(value) for key, value in targets.items()}}, indent=2), encoding='utf-8')
    print(f'Starting state saved: {snapshot_path}', flush=True)
    print(f'Pose {pose}: moving one finger at a time at {speed} deg/s. Ctrl+C stops the active finger.', flush=True)

    for finger in fingers:
        selected = [rows[2 * finger - 1], rows[2 * finger]]
        # Refresh after earlier fingers have moved, before enabling this pair.
        selected = [read_servo(controller, row['id']) for row in selected]
        for row in selected:
            validate_movement_servo(row, allow_voltage_warning)
        touched = []
        succeeded = False
        try:
            for row in selected:
                touched.append(row)
                controller.write_goal_speed(row['id'], math.radians(speed))
                controller.write_goal_position(row['id'], row['position'])
                if abs(read_one(controller, 'goal_position', row['id']) - row['position']) > math.radians(.5):
                    raise RuntimeError(f"ID {row['id']} did not accept its initial position.")
            for row in selected:
                controller.write_torque_enable(row['id'], 1)

            duration = max(abs(targets[row['id']] - row['position']) for row in selected) / math.radians(speed)
            steps = max(1, math.ceil(duration / .05))
            print(f'Finger {finger}: target {[round(math.degrees(targets[row["id"]]), 2) for row in selected]} deg', flush=True)
            for step in range(1, steps + 1):
                fraction = step / steps
                for row in selected:
                    goal = row['position'] + fraction * (targets[row['id']] - row['position'])
                    controller.write_goal_position(row['id'], goal)
                time.sleep(.05)
                if step % 4 == 0 or step == steps:
                    for row in selected:
                        actual = read_one(controller, 'present_position', row['id'])
                        goal = row['position'] + fraction * (targets[row['id']] - row['position'])
                        status = controller.read_register(row['id'], 'status')
                        load = abs(controller.read_register(row['id'], 'present_load'))
                        voltage = controller.read_register(row['id'], 'present_voltage')
                        temperature = controller.read_register(row['id'], 'present_temperature')
                        error_status = status & ~1 if allow_voltage_warning else status
                        minimum_voltage = 40 if allow_voltage_warning else row['min_voltage']
                        maximum_voltage = min(74, row['max_voltage']) if allow_voltage_warning else row['max_voltage']
                        if error_status != 0 or load > 500 or temperature >= 55 or not minimum_voltage <= voltage <= maximum_voltage:
                            raise RuntimeError(f"ID {row['id']} alarm/load/voltage check failed: status={status}, load={load}, voltage_raw={voltage}.")
                        if not math.isfinite(actual) or abs(actual - goal) > math.radians(8):
                            raise RuntimeError(f"ID {row['id']} fell over 8 degrees behind; stopping this finger.")
            def probe_endpoint():
                feedback = []
                for row in selected:
                    final = read_servo(controller, row['id'])
                    validate_movement_servo(final, allow_voltage_warning)
                    load = controller.read_register(row['id'], 'present_load')
                    goal = targets[row['id']]
                    if abs(load) > 500 or not math.isfinite(final['position']) or abs(final['position']-goal) > math.radians(8):
                        raise RuntimeError(f"ID {row['id']}: load/8-degree position check failed while settling.")
                    feedback.append(dict(id=row['id'], position=final['position'], goal=goal))
                return feedback
            wait_for_endpoint(probe_endpoint, end_tolerance, time.sleep)
            for row in selected:
                final = read_servo(controller, row['id'])
                validate_movement_servo(final, allow_voltage_warning)
                error = math.degrees(final['position'] - targets[row['id']])
                print(f"ID {row['id']}: position={math.degrees(final['position']):.2f} deg, target_error={error:+.2f} deg", flush=True)
                if abs(error) > end_tolerance:
                    load = controller.read_register(row['id'], 'present_load')
                    raise RuntimeError(
                        f"ID {row['id']} did not reach the {pose} pose within {end_tolerance} degrees: "
                        f"actual={math.degrees(final['position']):.2f}, "
                        f"target={math.degrees(targets[row['id']]):.2f}, "
                        f"error={error:+.2f} deg, load={load}, "
                        f"voltage={final['voltage']/10:.1f} V, status={final['status']}."
                    )
            succeeded = True
        finally:
            if not succeeded:
                for row in touched:
                    try:
                        controller.write_torque_enable(row['id'], 0)
                    except Exception as exc:
                        print(f"Could not release ID {row['id']}: {exc}", file=sys.stderr)

    for servo_id, target in targets.items():
        final = read_servo(controller, servo_id)
        validate_movement_servo(final, allow_voltage_warning)
        if abs(final['position'] - target) > math.radians(end_tolerance):
            raise RuntimeError(f'ID {servo_id} drifted away from the {pose} target.')
    label = ('OPEN_HAND_CONFIRMED' if len(selected_ids) == 8 else 'OPEN_FINGER_CONFIRMED' if len(selected_ids) == 2 else 'OPEN_FINGERS_CONFIRMED') if pose == 'open' else 'POSE_CONFIRMED'
    print(f'{label}: selected servos reached the requested targets within {end_tolerance} degrees. This verifies motor positions; visually check finger straightness. Torque stays enabled to hold the pose.', flush=True)


def cycle_hand(controller, rows, middle_positions):
    """One slow open/close/open cycle per finger; release all on any failure."""
    if set(rows) != set(range(1, 9)):
        raise RuntimeError('The four-finger cycle requires all eight servos.')
    for row in rows.values():
        validate_servo(row)
        for angle in (-35, 0, 45, 90):
            target = math.radians(middle_positions[row['id'] - 1] + (angle if row['id'] % 2 else -angle))
            if not row['min_angle'] <= target <= row['max_angle']:
                raise RuntimeError(f"Cycle target is outside ID {row['id']}'s limits.")
    try:
        for finger in range(1, 5):
            print(f'BEGIN_CYCLE finger={finger}', flush=True)
            move_pose(controller, rows, middle_positions, (finger,), -35, 'open', 4)
            for angle in (0, 45, 90):
                move_pose(controller, rows, middle_positions, (finger,), angle, 'close', 4)
            time.sleep(.3)
            move_pose(controller, rows, middle_positions, (finger,), -35, 'open', 4)
            print(f'FINGER_CYCLE_CONFIRMED finger={finger}', flush=True)
        print('HAND_CYCLE_CONFIRMED: all eight motors completed the targets. Visually confirm all finger joints. Holding the open pose.', flush=True)
    except BaseException:
        for servo_id in rows:
            try:
                controller.write_torque_enable(servo_id, 0)
            except Exception as exc:
                print(f'Could not release ID {servo_id}: {exc}', file=sys.stderr)
        raise


def move_finger(controller, rows, finger):
    ids = (2 * finger - 1, 2 * finger)
    if any(servo_id not in rows for servo_id in ids):
        raise RuntimeError(f'Finger {finger} requires responding servo IDs {ids}.')
    selected = [rows[servo_id] for servo_id in ids]
    offsets = [math.radians(3), math.radians(-3)]
    for row in selected:
        validate_servo(row)

    def within_limits(direction):
        return all(row['min_angle'] <= row['position'] <= row['max_angle']
                   and row['min_angle'] <= row['position'] + direction * offset <= row['max_angle']
                   for row, offset in zip(selected, offsets))

    direction = 1 if within_limits(1) else -1
    if not within_limits(direction):
        raise RuntimeError('No room for a 3-degree movement inside both servo limits.')
    touched = []
    succeeded = False
    try:
        # Set the current pose BEFORE enabling torque to avoid an old target jump.
        for row in selected:
            touched.append(row)
            controller.write_goal_speed(row['id'], math.radians(15))
            controller.write_goal_position(row['id'], row['position'])
            goal = read_one(controller, 'goal_position', row['id'])
            if abs(goal - row['position']) > math.radians(0.5):
                raise RuntimeError(f"ID {row['id']} did not accept the starting target.")
        for row in selected:
            controller.write_torque_enable(row['id'], 1)
        print(f'Moving finger {finger}: 3 degrees, then returning.', flush=True)
        for fraction in (0.25, 0.5, 0.75, 1.0):
            for row, offset in zip(selected, offsets):
                controller.write_goal_position(row['id'], row['position'] + direction * fraction * offset)
            time.sleep(0.10)
        time.sleep(0.20)
        measured = [read_one(controller, 'present_position', row['id']) for row in selected]
        for row, position in zip(selected, measured):
            print(f"ID {row['id']}: measured movement {math.degrees(position - row['position']):+.2f} deg", flush=True)
        for fraction in (0.75, 0.5, 0.25, 0.0):
            for row, offset in zip(selected, offsets):
                controller.write_goal_position(row['id'], row['position'] + direction * fraction * offset)
            time.sleep(0.10)
        time.sleep(0.25)
        returned = [read_one(controller, 'present_position', row['id']) for row in selected]
        if any(abs(position - row['position']) > math.radians(2) for row, position in zip(selected, returned)):
            raise RuntimeError('Feedback did not confirm a return to the starting pose.')
        if any((position - row['position']) * direction * offset <= 0
               or abs(position - row['position']) < math.radians(0.7)
               for row, position, offset in zip(selected, measured, offsets)):
            raise RuntimeError('3-degree test inconclusive: both servos must move at least 0.7 degrees in the commanded direction. Starting targets were restored; torque will be released. This does not by itself diagnose a servo fault.')
        succeeded = True
        print('MOVEMENT_CONFIRMED: both servos moved and returned.', flush=True)
    finally:
        for row in reversed(touched):
            try:
                # On interruption or failure, release the tested finger.
                controller.write_torque_enable(row['id'], row['torque'] if succeeded else 0)
                controller.write_goal_speed(row['id'], row['speed'])
            except Exception as exc:
                print(f"Could not restore ID {row['id']}: {exc}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--baudrate', type=int, default=1_000_000)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--move-finger', type=int, choices=range(1, 5), help='Perform one small movement; omit for read-only inspection.')
    action.add_argument('--open-hand', action='store_true', help='Slowly move all four fingers to OpenHand targets and hold.')
    action.add_argument('--open-three', action='store_true', help='Open index, middle and ring only at 4 deg/s; leave thumb commands unchanged.')
    action.add_argument('--cycle-hand', action='store_true', help='One monitored open/close/open cycle per finger at 4 deg/s; stop and release all on failure.')
    action.add_argument('--open-finger', type=int, choices=range(1, 5), help='Slowly open only the selected finger and hold.')
    action.add_argument('--release', action='store_true', help='Disable torque on the identified servos.')
    parser.add_argument('--extension', type=int, choices=(35, 37, 40), default=35, help='35: OpenHand; 37: a bounded 2-degree extension step; 40: index-only pointing reference.')
    parser.add_argument('--allow-voltage-warning', action='store_true', help='Allow only voltage status bit 0 within 4.0-7.4 V during opening; keep other checks and servo configuration.')
    parser.add_argument('--middle-pos', type=float, nargs=8, metavar='DEG', help='Calibrated offsets; defaults to MiddlePos in AmazingHand_Demo.py.')
    args = parser.parse_args()
    controller = Scs0009PyController(serial_port=args.port, baudrate=args.baudrate, timeout=0.15)
    try:
        print(f'Connected: {args.port}, {args.baudrate} baud', flush=True)
        rows = {}
        for servo_id in range(1, 9):
            try:
                if not controller.ping(servo_id):
                    print(f'ID {servo_id}: no response', flush=True)
                    continue
                row = read_servo(controller, servo_id)
                rows[servo_id] = row
                print(f"ID {servo_id}: model={row['model']}, position={math.degrees(row['position']):.2f} deg, "
                      f"voltage_raw={row['voltage']}, temperature={row['temperature']} C, torque={row['torque']}, status={row['status']}", flush=True)
            except Exception as exc:
                print(f'ID {servo_id}: {exc}', flush=True)
        if not rows:
            raise RuntimeError('No servos responded. Check servo power, TTL cable, baudrate and IDs.')
        if args.cycle_hand:
            cycle_hand(controller, rows, args.middle_pos if args.middle_pos is not None else default_middle_positions())
        elif args.open_three:
            open_hand(controller, rows, args.middle_pos if args.middle_pos is not None else default_middle_positions(), fingers=(1, 2, 3), extension=args.extension, speed=4, allow_voltage_warning=args.allow_voltage_warning)
        elif args.open_hand:
            open_hand(controller, rows, args.middle_pos if args.middle_pos is not None else default_middle_positions(), extension=args.extension, allow_voltage_warning=args.allow_voltage_warning)
        elif args.open_finger:
            open_hand(controller, rows, args.middle_pos if args.middle_pos is not None else default_middle_positions(), fingers=(args.open_finger,), extension=args.extension, allow_voltage_warning=args.allow_voltage_warning)
        elif args.release:
            for servo_id in rows:
                controller.write_torque_enable(servo_id, 0)
            print('Torque released on all identified servos.', flush=True)
        elif args.move_finger:
            move_finger(controller, rows, args.move_finger)
        else:
            print('Read-only inspection complete. No movement commands sent.', flush=True)
    finally:
        controller.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
