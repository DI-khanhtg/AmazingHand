"""Verify trajectory bounds and the SCS0009 telemetry decoder without hardware."""
import math
import unittest

from AmazingHand_Motion import motion_feedback, phase_at_fraction, smooth_fraction


class RawController:
    def __init__(self, position=825, load=-195, status=0, packet_error=0):
        encoded_load = abs(load) | (1024 if load < 0 else 0)
        self.raw = list(position.to_bytes(2, 'big')) + [0, 0] + list(encoded_load.to_bytes(2, 'big')) + [44, 32, 0, status]
        self.packet_error = packet_error

    def read_raw_data_with_error(self, servo_id, address, length):
        assert address == 56 and length == 10
        return self.raw, self.packet_error

    def word_order(self):
        return 'big'


class MotionTests(unittest.TestCase):
    def test_curve_has_smooth_ends_monotonic_progress_and_bounded_peak_speed(self):
        fractions = [smooth_fraction(i/1000) for i in range(1001)]
        self.assertEqual((fractions[0], fractions[-1]), (0, 1))
        self.assertTrue(all(a <= b for a, b in zip(fractions, fractions[1:])))
        self.assertLess(fractions[1], 1e-7)
        self.assertLess(1-fractions[-2], 1e-7)
        distance, peak_speed = 160, 40
        duration = 1.875*distance/peak_speed
        speeds = [(b-a)*distance/(duration/1000) for a,b in zip(fractions,fractions[1:])]
        self.assertLessEqual(max(speeds), peak_speed)

    def test_feedback_limited_phase_resumes_at_matching_fraction(self):
        for fraction in (0, .001, .1, .3, .5, .85, .999, 1):
            self.assertAlmostEqual(smooth_fraction(phase_at_fraction(fraction)), fraction, places=8)

    def test_block_decoder_matches_verified_rustypot_position_and_signed_load(self):
        for position in (0, 204, 511, 790, 825, 1023):
            for load in (-195, 0, 150):
                row = motion_feedback(RawController(position, load), 3, .5)
                self.assertEqual(row['id'], 3)
                self.assertAlmostEqual(row['position'], math.radians((position-511)*300/1024))
                self.assertEqual((row['goal'],row['load'],row['voltage'],row['temperature']), (.5, load, 44, 32))

    def test_both_packet_fault_and_register_status_are_preserved(self):
        self.assertEqual(motion_feedback(RawController(status=1, packet_error=32), 2, 0)['status'], 33)

    def test_malformed_or_out_of_range_feedback_stops(self):
        for controller in (RawController(position=1024), RawController()):
            if controller.raw[:2] != [4, 0]:
                controller.raw.pop()
            with self.assertRaises(RuntimeError):
                motion_feedback(controller, 1, 0)
