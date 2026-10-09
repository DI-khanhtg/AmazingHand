"""Smooth path interpolation and one-packet SCS0009 motion telemetry."""

import math

from AmazingHand_HardwareDemo import read_one


def smooth_fraction(phase):
    """Quintic easing: zero velocity and acceleration at both endpoints."""
    phase = max(0., min(1., phase))
    return phase**3 * (10. + phase * (-15. + 6. * phase))


def phase_at_fraction(fraction):
    """Resume virtual time at the actual, feedback-limited path fraction."""
    if fraction <= 0.:
        return 0.
    if fraction >= 1.:
        return 1.
    low, high = 0., 1.
    for _ in range(32):
        middle = (low+high)/2
        if smooth_fraction(middle) < fraction:
            low = middle
        else:
            high = middle
    return (low+high)/2


def motion_feedback(controller, servo_id, goal):
    """Read position/load/voltage/temperature/status in one read-only packet.

    SCS0009 control table: 56..65; position uses rustypot's SI conversion
    (raw - 511) * 300/1024 degrees. Load is sign-magnitude, sign bit 10.
    Startup model/angle checks remain in the caller before movement.
    """
    read_block = getattr(controller, 'read_raw_data_with_error', None)
    if read_block is None:
        # Older controllers and offline servo models retain the register API.
        return dict(id=servo_id, position=read_one(controller, 'present_position', servo_id), goal=goal,
                    status=controller.read_register(servo_id, 'status'),
                    load=controller.read_register(servo_id, 'present_load'),
                    voltage=controller.read_register(servo_id, 'present_voltage'),
                    temperature=controller.read_register(servo_id, 'present_temperature'))
    raw, packet_error = read_block(servo_id, 56, 10)
    if len(raw) != 10 or any(not isinstance(value, int) or not 0 <= value <= 255 for value in raw):
        raise RuntimeError(f'ID {servo_id}: malformed motion telemetry block; stopping servos.')
    byteorder = controller.word_order()
    position_raw = int.from_bytes(bytes(raw[:2]), byteorder)
    load_raw = int.from_bytes(bytes(raw[4:6]), byteorder)
    if not 0 <= position_raw <= 1023:
        raise RuntimeError(f'ID {servo_id}: invalid raw position {position_raw}; stopping servos.')
    magnitude = load_raw & 1023
    return dict(id=servo_id, position=math.radians((position_raw-511)*300/1024), goal=goal,
                status=raw[9] | packet_error, load=-magnitude if load_raw & 1024 else magnitude,
                voltage=raw[6], temperature=raw[7])
