"""Bound retries only for malformed read-only telemetry, preserving fault stops."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import AmazingHand_HardwareDemo as hardware
import AmazingHand_Notebook as notebook


class SerialFeedbackTests(unittest.TestCase):
    def test_transient_parser_error_recovers(self):
        row = {'id': 1}
        with patch.object(hardware, '_read_servo_once', side_effect=[RuntimeError('Parsing error'), row]) as read, \
             patch.object(hardware.time, 'sleep'):
            self.assertIs(hardware.read_servo(object(), 1), row)
        self.assertEqual(read.call_count, 2)

    def test_persistent_error_is_bounded_and_identifies_id(self):
        with patch.object(hardware, '_read_servo_once', side_effect=RuntimeError('Parsing error')) as read, \
             patch.object(hardware.time, 'sleep'):
            with self.assertRaisesRegex(hardware.SerialFeedbackError, 'ID 4:.*3 attempts'):
                hardware.read_servo(object(), 4)
        self.assertEqual(read.call_count, 3)

    def test_other_errors_are_not_retried(self):
        with patch.object(hardware, '_read_servo_once', side_effect=RuntimeError('wrong servo model')) as read:
            with self.assertRaisesRegex(RuntimeError, 'wrong servo model'):
                hardware.read_servo(object(), 1)
        self.assertEqual(read.call_count, 1)

    def test_inspect_failure_closes_port_without_commands(self):
        controller = Mock()
        with patch.object(notebook, 'Scs0009PyController', return_value=controller), \
             patch.object(notebook, 'read_servo', side_effect=hardware.SerialFeedbackError('bad reply')):
            with self.assertRaisesRegex(RuntimeError, 'COM3: servo ID 1'):
                notebook.NotebookHand().inspect()
        self.assertEqual([call[0] for call in controller.mock_calls], ['close'])


if __name__ == '__main__':
    unittest.main()
