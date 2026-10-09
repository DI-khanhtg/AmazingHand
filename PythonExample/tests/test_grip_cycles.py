"""Offline checks: never connect to a serial port or physical servos."""
import contextlib
import io
import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import AmazingHand_GripCycles as demo
import AmazingHand_Motion as motion


class FakeController:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []
        self.positions = [0.] * 8
        self.goals = [0.] * 8
        self.torque = [0] * 8

    def row(self, i):
        return dict(id=i, position=self.positions[i-1], torque=self.torque[i-1], speed=0.,
                    status=0, temperature=25, voltage=50, min_voltage=45,
                    max_voltage=90, min_angle=-2.6, max_angle=2.6)

    def read(self, name, i):
        if name == 'torque_enable':
            return self.torque[i-1]
        if name == 'goal_position':
            return self.goals[i-1]
        if name == 'present_position':
            return self.positions[i-1]
        raise AssertionError(name)

    def sync_write_goal_position(self, ids, values):
        assert ids == list(range(1, 9)) and len(values) == 8
        self.calls.append(('position', list(values)))
        if self.failure == 'interrupt' and any(self.torque):
            raise KeyboardInterrupt
        self.positions = list(values)
        self.goals = list(values)
        if self.failure == 'residual' and self.goals[2] > math.radians(75):
            self.positions[2] -= math.radians(3.26)

    def sync_write_goal_speed(self, ids, values):
        assert len(ids) == len(values) == 8
        self.calls.append(('speed', list(values)))

    def sync_write_torque_enable(self, ids, values):
        self.calls.append(('torque', list(values)))
        self.torque = list(values)

    def write_torque_enable(self, i, value):
        self.torque[i-1] = value

    def read_register(self, i, name):
        if name == 'present_voltage':
            if self.failure == 'below_range' and i == 2 and any(self.torque):
                return 39
            return 44 if self.failure == 'voltage' and i == 2 and any(self.torque) else 50
        status = 0
        if i == 2 and any(self.torque):
            status = {'alarm': 1, 'overload': 32, 'mixed_alarm': 5}.get(self.failure, 0)
        return dict(status=status,
                    present_load=50, present_temperature=25)[name]


class TrackingController(FakeController):
    """Finite motor speed instead of instantaneous target tracking."""
    def __init__(self, rate=12, stuck_id=None, disturbance=False):
        super().__init__()
        self.rate = math.radians(rate)
        self.stuck_id = stuck_id
        self.disturbance = disturbance
        self.maximum_lead = 0.

    def sync_write_goal_position(self, ids, values):
        positions = list(self.positions)
        super().sync_write_goal_position(ids, values)
        self.positions = positions
        if self.disturbance and any(self.torque):
            self.positions[0] = values[0] + math.radians(9)
        self.maximum_lead = max(self.maximum_lead, max(abs(a-b) for a,b in zip(self.positions, values)))

    def advance(self, seconds):
        for index, goal in enumerate(self.goals):
            if self.torque[index] and index+1 != self.stuck_id:
                error = goal-self.positions[index]
                self.positions[index] += math.copysign(min(abs(error), self.rate*seconds), error)


class GripCyclesTests(unittest.TestCase):
    def run_fake(self, controller, dry_run=False, ignore_low_voltage=False, allow_voltage_warning=False, end_tolerance=3, close_hold=False, open_hold=False, speed_deg_s=4, motion_profile='linear'):
        elapsed = [0.]
        def sleep(seconds):
            elapsed[0] += seconds
            if hasattr(controller, 'advance'):
                controller.advance(seconds)
        clock = SimpleNamespace(time_ns=time.time_ns, time=lambda: elapsed[0],
                                monotonic=lambda: elapsed[0], sleep=sleep)
        with patch.object(demo, 'time', clock), patch.object(demo, 'read_servo', side_effect=lambda c, i: c.row(i)), patch.object(demo, 'read_one', side_effect=lambda c, n, i: c.read(n, i)), patch.object(motion, 'read_one', side_effect=lambda c, n, i: c.read(n, i)), contextlib.redirect_stdout(io.StringIO()) as output:
            demo.run_cycles(controller, count=5, dry_run=dry_run, ignore_low_voltage=ignore_low_voltage, allow_voltage_warning=allow_voltage_warning, end_tolerance=end_tolerance, close_hold=close_hold, open_hold=open_hold, speed_deg_s=speed_deg_s, motion_profile=motion_profile)
            return output.getvalue()

    def test_fast_trajectory_waits_for_slower_motor_without_increasing_cutoff(self):
        c = TrackingController(rate=12)
        output = self.run_fake(c, open_hold=True, speed_deg_s=20)
        self.assertIn('slowing trajectory', output)
        self.assertIn('OPEN_HOLD_CONFIRMED', output)
        self.assertLessEqual(math.degrees(c.maximum_lead), 4.00001)
        self.assertEqual(c.torque, [1]*8)
        self.assertTrue(all(abs(a-b) < 1e-9 for a,b in zip(c.positions,c.goals)))

    def test_smooth_profile_paces_slower_motor_with_bounded_tracking_lead(self):
        c = TrackingController(rate=12)
        output = self.run_fake(c, open_hold=True, speed_deg_s=40, motion_profile='smooth', end_tolerance=4)
        self.assertIn('OPEN_HOLD_CONFIRMED', output)
        self.assertLessEqual(math.degrees(c.maximum_lead), 6.00001)
        self.assertEqual(c.torque, [1]*8)

    def test_smooth_profile_still_stops_on_stall_disturbance_and_other_faults(self):
        cases = [(TrackingController(stuck_id=1), 'no position progress'),
                 (TrackingController(disturbance=True), '8-degree'),
                 (FakeController('overload'), 'status=32'),
                 (FakeController('below_range'), '3.9 V')]
        for c, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, error):
                self.run_fake(c, open_hold=True, speed_deg_s=40, motion_profile='smooth', end_tolerance=4, allow_voltage_warning=True)
            self.assertEqual(c.torque, [0]*8)

    def test_smooth_packet_fault_or_corrupt_block_releases_every_motor(self):
        class BlockController(FakeController):
            def word_order(self):
                return 'big'

            def read_raw_data_with_error(self, i, address, length):
                position = round(511+math.degrees(self.positions[i-1])*1024/300)
                block = list(position.to_bytes(2, 'big')) + [0,0,0,50,50,25,0,0]
                active_failure = i == 2 and any(self.torque)
                if active_failure and self.failure == 'corrupt':
                    block.pop()
                return block, 32 if active_failure and self.failure == 'packet_alarm' else 0
        for failure, error in [('packet_alarm', 'status=32'), ('corrupt', 'malformed')]:
            with self.subTest(failure=failure):
                c = BlockController(failure)
                with self.assertRaisesRegex(RuntimeError, error):
                    self.run_fake(c, open_hold=True, speed_deg_s=40, motion_profile='smooth', end_tolerance=4, allow_voltage_warning=True)
                self.assertEqual(c.torque, [0]*8)

    def test_stuck_motor_still_stops_and_releases_all(self):
        for tolerance in (3, 4):
            with self.subTest(tolerance=tolerance):
                c = TrackingController(stuck_id=1)
                with self.assertRaisesRegex(RuntimeError, 'ID 1: no position progress'):
                    self.run_fake(c, open_hold=True, speed_deg_s=20, end_tolerance=tolerance)
                self.assertEqual(c.torque, [0]*8)

    def test_short_axis_inside_servo_deadband_waits_for_shared_trajectory(self):
        class Deadband(TrackingController):
            def advance(self, seconds):
                self.stuck_id = 1 if abs(self.goals[0]-self.positions[0]) <= math.radians(3.85) else None
                super().advance(seconds)
        c = Deadband(rate=12)
        c.positions[0] = math.radians(77)  # Only 16 degrees travel; other axes travel ~90.
        c.goals = list(c.positions)
        output = self.run_fake(c, close_hold=True, speed_deg_s=20, end_tolerance=4)
        self.assertIn('CLOSE_HOLD_CONFIRMED', output)
        self.assertEqual(c.torque, [1]*8)
        self.assertLessEqual(abs(math.degrees(c.positions[0]-c.goals[0])), 4)

    def test_finger_already_within_endpoint_tolerance_is_not_a_stall(self):
        c = TrackingController(stuck_id=3)
        c.positions[2] = math.radians(81.15)  # Target is 85; remaining error 3.85.
        c.goals = list(c.positions)
        output = self.run_fake(c, close_hold=True, speed_deg_s=20, end_tolerance=4)
        self.assertIn('CLOSE_HOLD_CONFIRMED', output)
        self.assertEqual(c.torque, [1]*8)
        self.assertAlmostEqual(math.degrees(c.positions[2]), 81.15)

    def test_tracking_horizon_does_not_create_false_midrange_stall(self):
        class StickyMiddle(TrackingController):
            released = False
            def advance(self, seconds):
                parked = self.positions[2] >= math.radians(21) and not self.released
                if parked and abs(self.goals[2]-self.positions[2]) > math.radians(5):
                    self.released = True
                    parked = False
                self.stuck_id = 3 if parked else None
                super().advance(seconds)
        c = StickyMiddle(rate=20)
        output = self.run_fake(c, close_hold=True, speed_deg_s=20)
        self.assertTrue(c.released)
        self.assertIn('6 degrees of tracking lead', output)
        self.assertIn('CLOSE_HOLD_CONFIRMED', output)
        self.assertGreater(math.degrees(c.maximum_lead), 5)
        self.assertLessEqual(math.degrees(c.maximum_lead), 6.00001)
        self.assertEqual(c.torque, [1]*8)

    def test_external_position_error_keeps_eight_degree_cutoff(self):
        c = TrackingController(disturbance=True)
        with self.assertRaisesRegex(RuntimeError, 'ID 1 exceeds 8-degree'):
            self.run_fake(c, open_hold=True, speed_deg_s=20)
        self.assertEqual(c.torque, [0]*8)

    def test_faster_speed_shortens_ramp_and_preserves_destination(self):
        slow, fast = FakeController(), FakeController()
        self.run_fake(slow, close_hold=True, speed_deg_s=4)
        self.run_fake(fast, close_hold=True, speed_deg_s=12)
        self.assertEqual(fast.positions, slow.positions)
        self.assertEqual(next(values for name, values in fast.calls if name == 'speed'),
                         [math.radians(12)] * 8)
        slow_steps = sum(name == 'position' for name, _ in slow.calls)
        fast_steps = sum(name == 'position' for name, _ in fast.calls)
        self.assertLess(fast_steps, slow_steps / 2)

    def test_invalid_speed_sends_no_commands(self):
        for speed in (0, -1, float('nan'), float('inf')):
            with self.subTest(speed=speed):
                controller = FakeController()
                with self.assertRaises(ValueError):
                    self.run_fake(controller, speed_deg_s=speed)
                self.assertEqual(controller.calls, [])

    def test_five_simultaneous_cycles_end_open(self):
        c = FakeController()
        output = self.run_fake(c)
        self.assertEqual(output.count('CYCLE_COMPLETE '), 5)
        middle = demo.default_middle_positions()
        opening = [math.radians(x + (-35 if i % 2 == 0 else 35)) for i, x in enumerate(middle)]
        closing = [math.radians(x + (90 if i % 2 == 0 else -90)) for i, x in enumerate(middle)]
        self.assertEqual(c.positions, opening)
        at_closed = [values == closing for name, values in c.calls if name == 'position']
        self.assertEqual(sum(value and (i == 0 or not at_closed[i-1]) for i, value in enumerate(at_closed)), 5)
        self.assertLess(next(i for i, (name, _) in enumerate(c.calls) if name == 'position'), next(i for i, (name, _) in enumerate(c.calls) if name == 'torque'))

    def test_undervoltage_stops_and_releases_all(self):
        c = FakeController('voltage')
        with self.assertRaisesRegex(RuntimeError, '4.4 V'):
            self.run_fake(c)
        self.assertEqual(c.torque, [0] * 8)
        self.assertEqual(sum(name == 'position' for name, _ in c.calls), 1)

    def test_interruption_releases_all(self):
        c = FakeController('interrupt')
        with self.assertRaises(KeyboardInterrupt):
            self.run_fake(c)
        self.assertEqual(c.torque, [0] * 8)

    def test_voltage_diagnostic_runs_five_cycles(self):
        c = FakeController('voltage')
        output = self.run_fake(c, ignore_low_voltage=True)
        self.assertEqual(output.count('CYCLE_COMPLETE '), 5)
        self.assertEqual(c.torque, [1] * 8)

    def test_voltage_diagnostic_keeps_servo_alarm_stop(self):
        c = FakeController('alarm')
        with self.assertRaisesRegex(RuntimeError, 'status=1'):
            self.run_fake(c, ignore_low_voltage=True)
        self.assertEqual(c.torque, [0] * 8)

    def test_voltage_warning_mode_runs_five_cycles(self):
        c = FakeController('alarm')
        output = self.run_fake(c, allow_voltage_warning=True)
        self.assertEqual(output.count('CYCLE_COMPLETE '), 5)

    def test_voltage_warning_mode_stops_for_other_faults(self):
        for failure in ('overload', 'mixed_alarm', 'below_range'):
            with self.subTest(failure=failure):
                c = FakeController(failure)
                with self.assertRaises(RuntimeError):
                    self.run_fake(c, allow_voltage_warning=True)
                self.assertEqual(c.torque, [0] * 8)

    def test_dry_run_sends_no_commands(self):
        c = FakeController()
        self.run_fake(c, dry_run=True)
        self.assertEqual(c.calls, [])

    def test_configurable_endpoint_tolerance(self):
        strict = FakeController('residual')
        with self.assertRaisesRegex(RuntimeError, '3-degree'):
            self.run_fake(strict)
        self.assertEqual(strict.torque, [0] * 8)
        c = FakeController('residual')
        output = self.run_fake(c, end_tolerance=4)
        self.assertEqual(output.count('CYCLE_COMPLETE '), 5)

    def test_settling_waits_for_late_arrival_without_relaxing_tolerance(self):
        class LateArrival(FakeController):
            pending = 0.
            def sync_write_goal_position(self, ids, values):
                super().sync_write_goal_position(ids, values)
                if values[2] >= math.radians(85):
                    self.positions[2] -= math.radians(3.26)
                    self.pending = 1.2

            def advance(self, seconds):
                if self.pending:
                    self.pending = max(0., self.pending-seconds)
                    if not self.pending:
                        self.positions = list(self.goals)

        c = LateArrival()
        self.assertIn('CLOSE_HOLD_CONFIRMED', self.run_fake(c, close_hold=True))
        self.assertEqual(c.positions, c.goals)
        self.assertEqual(c.torque, [1]*8)

    def test_fault_during_extended_settling_releases_every_motor(self):
        class LateFault(FakeController):
            settled = 0.
            def sync_write_goal_position(self, ids, values):
                super().sync_write_goal_position(ids, values)
                self.settled = 0.
                if values[2] >= math.radians(85):
                    self.positions[2] -= math.radians(3.26)

            def advance(self, seconds):
                self.settled += seconds

            def read_register(self, i, name):
                if name == 'status' and self.goals[2] >= math.radians(85) and self.settled >= 1.:
                    return 32
                return super().read_register(i, name)

        c = LateFault()
        with self.assertRaisesRegex(RuntimeError, 'status=32'):
            self.run_fake(c, close_hold=True)
        self.assertEqual(c.torque, [0]*8)

    def test_close_hold_does_not_reopen(self):
        c = FakeController()
        output = self.run_fake(c, close_hold=True)
        middle = demo.default_middle_positions()
        closing = [math.radians(x + (90 if i % 2 == 0 else -90)) for i, x in enumerate(middle)]
        self.assertEqual(c.positions, closing)
        self.assertEqual(c.torque, [1] * 8)
        self.assertIn('CLOSE_HOLD_CONFIRMED', output)
        self.assertNotIn('INITIAL_OPEN', output)
        self.assertNotIn('CYCLE_COMPLETE', output)

    def test_open_hold_from_closed_does_not_cycle(self):
        c = FakeController()
        middle = demo.default_middle_positions()
        c.positions = [math.radians(x + (90 if i % 2 == 0 else -90)) for i, x in enumerate(middle)]
        c.goals = list(c.positions)
        output = self.run_fake(c, open_hold=True)
        opening = [math.radians(x + (-35 if i % 2 == 0 else 35)) for i, x in enumerate(middle)]
        self.assertEqual(c.positions, opening)
        self.assertEqual(c.torque, [1] * 8)
        self.assertIn('OPEN_HOLD_CONFIRMED', output)
        self.assertNotIn('CLOSE_HAND', output)
        self.assertNotIn('CYCLE_COMPLETE', output)


if __name__ == '__main__':
    unittest.main()
