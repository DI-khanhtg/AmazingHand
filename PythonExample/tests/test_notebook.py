"""Execute the delivered notebook with fake servos; never open a hardware port."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'PythonExample'))
import AmazingHand_Notebook as helper
from test_grip_cycles import FakeController


class NotebookTests(unittest.TestCase):
    def test_notebook_executes_every_cell_with_mock_hardware(self):
        nb = nbformat.read(ROOT / 'PythonExample' / 'AmazingHand_Control.ipynb', as_version=4)
        nbformat.validate(nb)
        code_cells = [cell for cell in nb.cells if cell.cell_type == 'code']
        self.assertEqual(len(code_cells), 13)  # Setup, seven gestures, four single-finger tests, release.
        for cell in code_cells:
            cell.outputs = []
            cell.execution_count = None
        bootstrap = '''from pathlib import Path
import sys
import time as real_time
from types import SimpleNamespace
sys.path.insert(0, str(Path.cwd() / "PythonExample"))
sys.path.insert(0, str(Path.cwd() / "PythonExample" / "tests"))
import rustypot
import AmazingHand_Notebook as n
import AmazingHand_GripCycles as g
from test_open_three import FakePoseController
import AmazingHand_HardwareDemo as h

def forbidden_hardware(*args, **kwargs):
    raise AssertionError("Tests must never connect to real hardware")
rustypot.Scs0009PyController = forbidden_hardware

instances = []
class MockController(FakePoseController):
    def __init__(self, **kwargs):
        super().__init__()
        self.closed = False
        instances.append(self)
    def close(self):
        self.closed = True
n.Scs0009PyController = MockController
n.read_servo = g.read_servo = lambda c, i: c.row(i)
n.read_one = g.read_one = lambda c, name, i: c.read(name, i)
h.read_servo = n.read_servo
h.read_one = n.read_one
elapsed = [0.]
def advance(seconds):
    elapsed[0] += seconds
g.time = SimpleNamespace(time_ns=real_time.time_ns, time=lambda: elapsed[0],
                         monotonic=lambda: elapsed[0], sleep=advance)
h.time = g.time

# Simulate the user's already-running kernel holding the older class.
class LegacyNotebookHand:
    def __init__(self, port='COM3'):
        pass
n.NotebookHand = LegacyNotebookHand

# Reload the real code, then reconnect the fake hardware/clock after each reload.
# The real serial constructor remains forbidden throughout the notebook test.
import importlib
real_reload = importlib.reload
def reload_with_mock_hardware(module):
    module = real_reload(module)
    if module.__name__ in ('AmazingHand_HardwareDemo', 'AmazingHand_Motion', 'AmazingHand_GripCycles', 'AmazingHand_Notebook'):
        module.read_servo = lambda c, i: c.row(i)
        module.read_one = lambda c, name, i: c.read(name, i)
    if module.__name__ in ('AmazingHand_HardwareDemo', 'AmazingHand_GripCycles'):
        module.time = g.time if module is not g else fake_clock
    if module.__name__ == 'AmazingHand_Notebook':
        module.Scs0009PyController = MockController
    return module
fake_clock = g.time
importlib.reload = reload_with_mock_hardware
'''
        assertions = '''import math
expected = [
    [-64, 67, -63, 50, -39, 42, -47, 35],
    [95, -92, 85, -98, 88, -85, 78, -90],
    [-49, 82, -78, 35, 88, -85, 78, -90],
    [-64, 67, 85, -98, 88, -85, 78, -90],
    [95, -92, -63, 50, 88, -85, 78, -90],
    [95, -92, 85, -98, -39, 42, 78, -90],
    [95, -92, 85, -98, 88, -85, -47, 35],
]
assert len(instances) == 13
assert all(c.closed for c in instances)
assert instances[0].calls == []  # Setup reads only.
for controller, angles in zip(instances[1:8], expected):
    assert controller.positions == list(map(math.radians, angles))
    assert controller.torque == [1] * 8
    assert next(values for name, values in controller.calls if name == 'speed') == [math.radians(40)] * 8
for controller, ids, angles in zip(instances[8:12], [(1,2), (1,2), (3,4), (3,4)],
                                  [(-64,67), (95,-92), (-63,50), (85,-98)]):
    assert set(controller.written_ids) == set(ids)
    assert [controller.positions[i-1] for i in ids] == list(map(math.radians, angles))
assert instances[-1].torque == [0] * 8
print("All seven gestures and serial connection cleanup verified offline.")
'''
        nb.cells.insert(0, nbformat.v4.new_code_cell(bootstrap))
        nb.cells.append(nbformat.v4.new_code_cell(assertions))
        NotebookClient(nb, timeout=60, kernel_name='amazinghand',
                       resources={'metadata': {'path': str(ROOT)}}).execute()

    def test_error_closes_port_after_motion_failure(self):
        controller = FakeController()
        controller.close = lambda: setattr(controller, 'closed', True)
        with patch.object(helper, 'Scs0009PyController', return_value=controller), \
             patch.object(helper, 'run_cycles', side_effect=RuntimeError('motion failed')):
            with self.assertRaisesRegex(RuntimeError, 'motion failed'):
                helper.NotebookHand().open_all()
        self.assertTrue(controller.closed)

    def test_endpoint_tolerance_is_consistent_for_gestures_and_single_finger(self):
        hand = helper.NotebookHand(end_tolerance=4)
        controller = FakeController()
        with patch.object(hand, '_connection') as connection, \
             patch.object(helper, 'run_cycles') as cycles, \
             patch.object(helper, 'move_pose') as move, \
             patch.object(helper, 'read_servo', side_effect=lambda c, i: c.row(i)), \
             patch.object(helper, 'read_one', side_effect=lambda c, n, i: c.read(n, i)):
            connection.return_value.__enter__.return_value = controller
            hand.close_all()
            hand.test_finger('middle', 'close')
        self.assertEqual(cycles.call_args.kwargs['end_tolerance'], 4)
        self.assertEqual(move.call_args.kwargs['end_tolerance'], 4)

    def test_adjustment_is_not_committed_after_failed_move(self):
        hand = helper.NotebookHand()
        before = hand.close_flexions
        with patch.object(hand, '_move_single', side_effect=RuntimeError('endpoint not reached')):
            with self.assertRaisesRegex(RuntimeError, 'endpoint not reached'):
                hand.adjust_endpoint('middle', 'close', delta=1)
        self.assertEqual(hand.close_flexions, before)

    def test_successful_adjustment_updates_only_selected_endpoint(self):
        hand = helper.NotebookHand()
        with patch.object(hand, '_move_single', return_value=[]):
            hand.adjust_endpoint('index', 'open', delta=1)
        self.assertEqual(hand.open_extensions, (68, 58, 37, 35))
        self.assertEqual(hand.close_flexions, (92, 90, 90, 90))

    def test_dry_run_adjustment_never_commits_profile(self):
        hand = helper.NotebookHand(dry_run=True)
        with patch.object(hand, '_move_single', return_value=[]):
            hand.adjust_endpoint('middle', 'open', delta=1)
        self.assertEqual(hand.open_extensions, (67, 58, 37, 35))

    def test_adjustment_limits_are_checked_before_connecting(self):
        hand = helper.NotebookHand()
        with patch.object(helper, 'Scs0009PyController') as connect:
            for delta in (0, 3, float('nan')):
                with self.subTest(delta=delta), self.assertRaises(ValueError):
                    hand.adjust_endpoint('index', 'open', delta=delta)
        connect.assert_not_called()

    def test_v_sign_uses_configured_folded_finger_endpoints(self):
        hand = helper.NotebookHand(close_flexions=(92, 90, 91, 89))
        with patch.object(hand, '_hold') as hold:
            hand.v_sign()
        self.assertEqual(hold.call_args.args[0][4:], [89, -86, 77, -89])

    def test_release_attempts_remaining_ids_after_one_write_fails(self):
        controller = FakeController()
        attempted = []
        def write(i, value):
            attempted.append(i)
            if i == 2:
                raise RuntimeError('disconnected')
        controller.write_torque_enable = write
        controller.close = lambda: setattr(controller, 'closed', True)
        with patch.object(helper, 'Scs0009PyController', return_value=controller), \
             patch.object(helper, 'read_one', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'ID 2'):
                helper.NotebookHand().release()
        self.assertEqual(attempted, list(range(1, 9)))
        self.assertTrue(controller.closed)


if __name__ == '__main__':
    unittest.main()
