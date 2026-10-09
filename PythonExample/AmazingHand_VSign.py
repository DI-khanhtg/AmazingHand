"""Hold a V/peace sign: index and middle up, ring and thumb folded."""

import argparse
import math
import sys

from rustypot import Scs0009PyController
from AmazingHand_HardwareDemo import default_middle_positions
from AmazingHand_GripCycles import run_cycles


def v_targets(side='right', extension=39, spread=15):
    """Use the differential-angle pattern of Victory() in the original demo."""
    if side not in ('right', 'left'):
        raise ValueError('Side must be right or left.')
    if not math.isfinite(extension) or not 35 <= extension <= 70:
        raise ValueError('Extension must be 35 to 70 degrees.')
    if not math.isfinite(spread) or not 0 <= spread <= 25:
        raise ValueError('Spread must be 0 to 25 degrees.')
    direction = 1 if side == 'right' else -1
    separation = direction * spread
    relative = [-extension + separation, extension + separation,
                -extension - separation, extension - separation,
                90, -90, 90, -90]
    return [offset + angle for offset, angle in zip(default_middle_positions(), relative)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--side', choices=('right', 'left'), default='right')
    parser.add_argument('--extension', type=float, default=39, help='Index/middle extension, 35-70 deg; default preserves the original CLI pose.')
    parser.add_argument('--spread', type=float, default=15, help='V separation, 0-25 deg; 0 keeps index/middle parallel.')
    parser.add_argument('--dry-run', action='store_true', help='Read servo telemetry and validate the pose, without movement or torque writes.')
    parser.add_argument('--allow-voltage-warning', action='store_true', help='Use the previously tested diagnostic handling of voltage bit 0 within 4.0-7.4 V. Other checks remain enabled.')
    args = parser.parse_args()
    targets = v_targets(args.side, args.extension, args.spread)
    print(f'V_SIGN targets ID 1-8: {[round(x,2) for x in targets]} deg', flush=True)
    controller = Scs0009PyController(serial_port=args.port, baudrate=1_000_000, timeout=.2)
    try:
        run_cycles(controller, count=1, dry_run=args.dry_run,
                   allow_voltage_warning=args.allow_voltage_warning, end_tolerance=4,
                   custom_target_degrees=targets, pose_label='V_SIGN')
    finally:
        controller.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped; attempted to release torque if movement had started.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
