"""Verify selective opening without any serial-port access."""
import contextlib
import io
import math
import unittest
from unittest.mock import patch

from test_grip_cycles import FakeController
import AmazingHand_HardwareDemo as demo


class FakePoseController(FakeController):
    def __init__(self, failure=None):
        super().__init__(failure)
        self.written_ids = []

    def write_goal_position(self, i, value):
        self.written_ids.append(i)
        self.positions[i-1] = self.goals[i-1] = value

    def write_goal_speed(self, i, value):
        self.written_ids.append(i)

    def write_torque_enable(self, i, value):
        self.written_ids.append(i)
        super().write_torque_enable(i, value)

    def read_register(self, i, name):
        if self.failure == 'alarm' and i == 2 and name == 'present_voltage':
            return 44
        return super().read_register(i, name)


class OpenThreeTests(unittest.TestCase):
    def run_open(self, c, allow_warning):
        middle = demo.default_middle_positions()
        c.positions = [math.radians(x + (-35 if i % 2 == 0 else 35)) for i, x in enumerate(middle)]
        c.goals = list(c.positions)
        c.torque = [1] * 8
        with patch.object(demo, 'read_servo', side_effect=lambda c, i: c.row(i)), patch.object(demo, 'read_one', side_effect=lambda c, n, i: c.read(n, i)), patch.object(demo.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            demo.open_hand(c, {i:c.row(i) for i in range(1,9)}, middle, fingers=(1,2,3), extension=37, speed=4, allow_voltage_warning=allow_warning)

    def test_three_extend_and_thumb_commands_unchanged(self):
        c = FakePoseController('alarm')
        self.run_open(c, True)
        self.assertEqual(set(c.written_ids), set(range(1,7)))
        middle = demo.default_middle_positions()
        for i in range(8):
            extension = 37 if i < 6 else 35
            self.assertAlmostEqual(c.positions[i], math.radians(middle[i] + (-extension if i % 2 == 0 else extension)))
        self.assertEqual(c.torque, [1] * 8)

    def test_other_servo_alarm_stops_active_pair(self):
        c = FakePoseController('overload')
        with self.assertRaises(RuntimeError):
            self.run_open(c, True)
        self.assertEqual(c.torque[:2], [0,0])
        self.assertTrue(set(c.written_ids).issubset({1,2}))


if __name__ == '__main__':
    unittest.main()
