"""Open all four fingers, then perform bounded simultaneous close/open cycles."""

import argparse
import json
import math
from pathlib import Path
import sys
import time

from rustypot import Scs0009PyController
from AmazingHand_HardwareDemo import default_middle_positions, read_one, read_servo, validate_servo, wait_for_endpoint
from AmazingHand_Motion import motion_feedback, smooth_fraction, phase_at_fraction


def run_cycles(controller, count=5, dry_run=False, ignore_low_voltage=False, allow_voltage_warning=False, end_tolerance=3, close_hold=False, open_hold=False, custom_target_degrees=None, pose_label='CUSTOM', speed_deg_s=4, motion_profile='linear'):
    if not math.isfinite(speed_deg_s) or speed_deg_s <= 0:
        raise ValueError('Speed must be a finite positive number of degrees per second.')
    if motion_profile not in ('linear', 'smooth'):
        raise ValueError('Motion profile must be linear or smooth.')
    smooth = motion_profile == 'smooth'
    update_interval = .02 if smooth else .1
    if close_hold and open_hold:
        raise ValueError('Choose only one hold pose.')
    if custom_target_degrees is not None and (close_hold or open_hold):
        raise ValueError('Custom pose cannot be combined with open/close hold.')
    if custom_target_degrees is not None:
        if len(custom_target_degrees) != 8 or not all(math.isfinite(x) for x in custom_target_degrees):
            raise ValueError('Custom pose needs eight finite angles in degrees.')
    hold_pose = 'custom' if custom_target_degrees is not None else 'close' if close_hold else 'open' if open_hold else None
    if count not in range(1, 6):
        raise ValueError('Choose 1 to 5 cycles.')
    if end_tolerance not in (3, 4, 5):
        raise ValueError('Endpoint tolerance must be 3, 4 or 5 degrees.')
    ignore_low_voltage = ignore_low_voltage or allow_voltage_warning
    ids = list(range(1, 9))
    rows = {i: read_servo(controller, i) for i in ids}
    middle = default_middle_positions()
    targets = {pose: [math.radians(middle[i - 1] + (angle if i % 2 else -angle))
                      for i in ids] for pose, angle in (('open', -35), ('close', 90))}
    if custom_target_degrees is not None:
        targets = {'custom': list(map(math.radians, custom_target_degrees))}
    for i in ids:
        validation_row = dict(rows[i])
        if ignore_low_voltage:
            validation_row['min_voltage'] = 0
        if allow_voltage_warning:
            # FEETECH SCS0009 input range: 4.0-7.4 V; only voltage bit 0 may pass.
            validation_row['min_voltage'] = max(40, validation_row['min_voltage'])
            validation_row['max_voltage'] = min(74, validation_row['max_voltage'])
            validation_row['status'] &= ~1
        validate_servo(validation_row)
        for pose, values in targets.items():
            if not rows[i]['min_angle'] <= values[i - 1] <= rows[i]['max_angle']:
                raise RuntimeError(f'ID {i}: {pose} target exceeds configured limits.')
    if dry_run:
        print('DRY_RUN: all eight servos and requested targets checked; no commands sent.', flush=True)
        return

    directory = Path(__file__).resolve().parent.parent / '.tools' / 'hardware'
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    state_path = directory / f'before-grip-cycles-{stamp}.json'
    state_path.write_text(json.dumps({'servos': rows, 'cycles': 0 if hold_pose else count,
                                    'action': f'{hold_pose}_hold' if hold_pose else 'grip_cycles',
                                    'pose_label': pose_label if hold_pose == 'custom' else hold_pose,
                                    'ignore_low_voltage': ignore_low_voltage,
                                    'allow_voltage_warning': allow_voltage_warning,
                                    'end_tolerance_degrees': end_tolerance,
                                    'speed_deg_s': speed_deg_s,
                                    'motion_profile': motion_profile,
                                    'update_interval_s': update_interval,
                                    'target_degrees': {k: list(map(math.degrees, v)) for k, v in targets.items()}}, indent=2), encoding='utf-8')
    print(f'State saved: {state_path}', flush=True)
    if hold_pose:
        print(f'All four fingers together: {hold_pose} once at {speed_deg_s:g} deg/s, then hold the pose.', flush=True)
    else:
        print(f'All four fingers together: initial open, then {count} close/open cycles at {speed_deg_s:g} deg/s.', flush=True)
    if ignore_low_voltage and not allow_voltage_warning:
        print('DIAGNOSTIC: software low-voltage cutoff disabled for this run. Servo alarms, high voltage, load, temperature and position checks remain enabled. Servo configuration is unchanged.', flush=True)
    if allow_voltage_warning:
        print('DIAGNOSTIC: only voltage status bit 0 may pass within 4.0-7.4 V. All other status bits remain fatal. No EEPROM writes.', flush=True)
    touched = False
    succeeded = False
    with (directory / f'grip-feedback-{stamp}.jsonl').open('w', encoding='utf-8', buffering=1) as log:
        def check(goals, tolerance=8):
            feedback = []
            for i, goal in zip(ids, goals):
                if smooth:
                    feedback.append(motion_feedback(controller, i, goal))
                else:
                    feedback.append(dict(id=i, position=read_one(controller, 'present_position', i), goal=goal,
                                     status=controller.read_register(i, 'status'),
                                     load=controller.read_register(i, 'present_load'),
                                     voltage=controller.read_register(i, 'present_voltage'),
                                     temperature=controller.read_register(i, 'present_temperature')))
            log.write(json.dumps({'time': time.time(), 'feedback': feedback}) + '\n')
            for row in feedback:
                i = row['id']
                status = row['status'] & ~1 if allow_voltage_warning else row['status']
                outside_operating_range = allow_voltage_warning and not 40 <= row['voltage'] <= 74
                low_voltage = row['voltage'] < rows[i]['min_voltage'] and not ignore_low_voltage
                if status or outside_operating_range or abs(row['load']) > 500 or row['temperature'] >= 55 or low_voltage or row['voltage'] > rows[i]['max_voltage']:
                    raise RuntimeError(f"ID {i}: status={row['status']}, load={row['load']}, voltage={row['voltage']/10:.1f} V, temperature={row['temperature']} C; stopping all servos.")
                if not math.isfinite(row['position']) or abs(row['position'] - row['goal']) > math.radians(tolerance):
                    raise RuntimeError(
                        f"ID {i} exceeds {tolerance}-degree position tolerance: "
                        f"actual={math.degrees(row['position']):.2f}, "
                        f"goal={math.degrees(row['goal']):.2f}, "
                        f"error={math.degrees(row['position']-row['goal']):+.2f} deg; stopping all servos."
                    )
            return feedback

        def move(pose, label):
            start = [read_one(controller, 'present_position', i) for i in ids]
            destination = targets[pose]
            travel = [b-a for a, b in zip(start, destination)]
            maximum_travel = max(map(abs, travel))
            # Peak derivative of the quintic curve is 1.875. Scaling duration
            # keeps its peak command velocity within the requested speed ceiling.
            duration = maximum_travel / math.radians(speed_deg_s) * (1.875 if smooth else 1.)
            print(f'{label}: simultaneous {pose}, {motion_profile}, nominal {duration:.1f} s; pacing follows servo feedback.', flush=True)
            began = time.monotonic()
            last_tick = began
            deadline = began + max(10., 3 * duration + 5.)
            fraction = 0.
            phase = 0.
            feedback = check(start)
            anchors = [row['position'] for row in feedback]
            last_progress = [began] * len(ids)
            pending_since = [None] * len(ids)
            # Dense smooth updates use the already-tested 6-degree tracking
            # horizon throughout, retaining the independent 8-degree cutoff.
            tracking_leads = [math.radians(6 if smooth else 4)] * len(ids)
            adjusted = False
            while True:
                now = time.monotonic()
                if now > deadline:
                    raise RuntimeError(f'{label}: movement timed out; stopping all servos.')
                # Advance at the requested rate, with no large jumps after USB delays.
                elapsed = min(.05 if smooth else .2, max(0., now-last_tick))
                last_tick = now
                proposed_phase = min(1., phase + elapsed/duration) if duration else 1.
                requested = (smooth_fraction(proposed_phase) if smooth else
                             min(1., fraction + elapsed/duration) if duration else 1.)
                candidate = requested
                # All motors keep a common interpolation fraction. Pause before the
                # requested goals get ahead of the bounded tracking horizon.
                # Linear mode starts at 4 degrees, with one 6-degree breakaway
                # allowance; smooth mode uses 6. The 8-degree cutoff stays active.
                for row, origin, delta, lead in zip(feedback, start, travel, tracking_leads):
                    if abs(delta) > 1e-12:
                        progress = (row['position']-origin) / delta
                        candidate = min(candidate, progress + lead/abs(delta))
                candidate = max(fraction, min(1., candidate))
                if duration and candidate < requested - 1e-9 and not adjusted:
                    print(f'{label}: slowing trajectory to let servos catch up (speed ceiling {speed_deg_s:g} deg/s).', flush=True)
                    adjusted = True
                fraction = candidate
                if smooth:
                    phase = proposed_phase if candidate >= requested-1e-12 else phase_at_fraction(candidate)
                goals = list(destination) if fraction == 1. else [a + fraction * (b - a) for a, b in zip(start, destination)]
                controller.sync_write_goal_position(ids, goals)
                feedback = check(goals)
                if fraction == 1.:
                    break
                observed = time.monotonic()
                for index, row in enumerate(feedback):
                    needs_motion = abs(row['position']-destination[index]) > math.radians(end_tolerance)
                    # A finger already inside its endpoint tolerance can remain
                    # still while the other fingers finish the common trajectory.
                    # Its servo deadband must not start a false stall countdown.
                    if not needs_motion:
                        anchors[index] = row['position']
                        last_progress[index] = observed
                        pending_since[index] = None
                    if abs(row['position']-anchors[index]) >= math.radians(.5):
                        anchors[index] = row['position']
                        last_progress[index] = observed
                        pending_since[index] = None
                    # A small tracking horizon can itself prevent breakaway under
                    # load. Allow one bounded 6-degree horizon before declaring a
                    # stall; never relax the separate 8-degree fault cutoff.
                    if (needs_motion and abs(row['position']-row['goal']) > math.radians(2.5)
                            and observed-last_progress[index] > .75
                            and tracking_leads[index] < math.radians(6)):
                        tracking_leads[index] = math.radians(6)
                        print(f"ID {row['id']}: allowing up to 6 degrees of tracking lead to test breakaway; hard cutoff stays 8 degrees.", flush=True)
                    # Count a stall only while the CURRENT command asks for
                    # movement outside the accepted position tolerance. A short
                    # axis in the shared trajectory may remain inside the servo
                    # deadband for seconds while a longer axis moves normally.
                    meaningful_pending = needs_motion and abs(row['position']-row['goal']) > math.radians(end_tolerance)
                    if not meaningful_pending:
                        pending_since[index] = None
                    elif pending_since[index] is None:
                        pending_since[index] = observed
                    elif observed-pending_since[index] > 2.:
                        raise RuntimeError(
                            f"ID {row['id']}: no position progress for 2 seconds despite a pending target: "
                            f"actual={math.degrees(row['position']):.2f}, goal={math.degrees(row['goal']):.2f}, "
                            f"load={row['load']}, voltage={row['voltage']/10:.1f} V, status={row['status']}; stopping all servos."
                        )
                time.sleep(update_interval)
            feedback = wait_for_endpoint(lambda: check(destination), end_tolerance, time.sleep)
            error = max(abs(math.degrees(row['position'] - row['goal'])) for row in feedback)
            print(f'{label}_CONFIRMED: all eight motors within {error:.2f} deg of target.', flush=True)

        try:
            start = [rows[i]['position'] for i in ids]
            touched = True
            controller.sync_write_goal_speed(ids, [math.radians(speed_deg_s)] * 8)
            # Accept current-position goals before torque, preventing old-target jumps.
            controller.sync_write_goal_position(ids, start)
            for i, position in zip(ids, start):
                if abs(read_one(controller, 'goal_position', i) - position) > math.radians(.5):
                    raise RuntimeError(f'ID {i} did not accept its starting target.')
            controller.sync_write_torque_enable(ids, [1] * 8)
            for i in ids:
                if read_one(controller, 'torque_enable', i) != 1:
                    raise RuntimeError(f'ID {i} did not enable torque.')
            check(start)
            if hold_pose:
                move(hold_pose, pose_label if hold_pose == 'custom' else f'{hold_pose.upper()}_HAND')
                for _ in range(20):
                    time.sleep(.1)
                    check(targets[hold_pose], tolerance=end_tolerance)
            else:
                move('open', 'INITIAL_OPEN')
                for cycle in range(1, count + 1):
                    move('close', f'CYCLE_{cycle}_CLOSE')
                    move('open', f'CYCLE_{cycle}_OPEN')
                    print(f'CYCLE_COMPLETE {cycle}/{count}', flush=True)
            succeeded = True
            if hold_pose:
                label = pose_label if hold_pose == 'custom' else hold_pose.upper()
                print(f'{label}_HOLD_CONFIRMED: all eight motors reached the pose and held it. Torque stays enabled. Visually confirm the finger joints.', flush=True)
            else:
                print(f'GRIP_CYCLES_CONFIRMED: {count} cycles completed; holding open. Visually confirm joint movement.', flush=True)
        finally:
            if touched and not succeeded:
                for i in ids:
                    try:
                        controller.write_torque_enable(i, 0)
                    except Exception as exc:
                        print(f'Could not release ID {i}: {exc}', file=sys.stderr)
                print('STOPPED: attempted torque release for all eight servos; no further cycles.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--cycles', type=int, choices=range(1, 6), default=5)
    hold = parser.add_mutually_exclusive_group()
    hold.add_argument('--close-hold', action='store_true', help='Close all four fingers once to repository CloseHand targets and hold, without opening or cycling.')
    hold.add_argument('--open-hold', action='store_true', help='Open all four fingers once to repository OpenHand targets and hold, without closing or cycling.')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--ignore-low-voltage', action='store_true', help='Disable only the software low-voltage cutoff for this diagnostic run; keep servo alarms and other checks.')
    parser.add_argument('--allow-voltage-warning', action='store_true', help='Diagnostic: also permit only voltage status bit 0 within the manufacturer 4.0-7.4 V operating range; preserve all other checks and servo configuration.')
    parser.add_argument('--end-tolerance', type=int, choices=(3, 4, 5), default=3, help='Endpoint confirmation tolerance in degrees; moving-position cutoff stays at 8 degrees.')
    args = parser.parse_args()
    controller = Scs0009PyController(serial_port=args.port, baudrate=1_000_000, timeout=.2)
    try:
        run_cycles(controller, args.cycles, args.dry_run, args.ignore_low_voltage, args.allow_voltage_warning, args.end_tolerance, args.close_hold, args.open_hold)
    finally:
        controller.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
