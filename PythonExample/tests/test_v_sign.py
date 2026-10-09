"""Offline gesture checks: no hardware or serial ports are opened."""
import contextlib
import io
import math
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_grip_cycles import FakeController
import AmazingHand_GripCycles as movement
from AmazingHand_VSign import v_targets


class VSignTests(unittest.TestCase):
    def run_fake(self, c, targets, dry_run=False):
        elapsed = [0.]
        def sleep(seconds):
            elapsed[0] += seconds
        clock = SimpleNamespace(time_ns=time.time_ns, time=lambda:elapsed[0],
                                monotonic=lambda:elapsed[0], sleep=sleep)
        with patch.object(movement, 'time', clock), patch.object(movement, 'read_servo', side_effect=lambda c,i:c.row(i)), patch.object(movement, 'read_one', side_effect=lambda c,n,i:c.read(n,i)), contextlib.redirect_stdout(io.StringIO()) as output:
            movement.run_cycles(c, count=1, dry_run=dry_run, allow_voltage_warning=True,
                                end_tolerance=4, custom_target_degrees=targets, pose_label='V_SIGN')
            return output.getvalue()

    def test_original_victory_reference_for_both_sides(self):
        self.assertEqual(v_targets('right',40,25), [-12,65,-70,7,88,-85,78,-90])
        self.assertEqual(v_targets('left',40,25), [-62,15,-20,57,88,-85,78,-90])

    def test_default_v_holds_without_cycles(self):
        targets = v_targets()
        c = FakeController()
        output = self.run_fake(c, targets)
        self.assertEqual(c.positions, list(map(math.radians,targets)))
        self.assertEqual(c.torque, [1]*8)
        self.assertIn('V_SIGN_HOLD_CONFIRMED', output)
        self.assertNotIn('CYCLE_COMPLETE', output)

    def test_dry_run_sends_no_commands(self):
        c = FakeController()
        self.run_fake(c, v_targets(), dry_run=True)
        self.assertEqual(c.calls, [])

    def test_overload_releases_all(self):
        c = FakeController('overload')
        with self.assertRaises(RuntimeError):
            self.run_fake(c, v_targets())
        self.assertEqual(c.torque, [0]*8)

    def test_target_outside_limits_sends_no_commands(self):
        c = FakeController()
        targets = v_targets(); targets[0] = 180
        with self.assertRaises(RuntimeError):
            self.run_fake(c, targets)
        self.assertEqual(c.calls, [])

    def test_invalid_gesture_parameters(self):
        for args in (('right',34,15), ('right',39,26), ('left',float('nan'),15)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                v_targets(*args)


if __name__ == '__main__':
    unittest.main()
