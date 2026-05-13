"""rclpy entrypoint.

M1: this is a thin skeleton. It can be imported without rclpy installed
(the ROS2 imports are deferred to ``main()``). Real publish/subscribe
wiring lands in M3.
"""

from __future__ import annotations

import argparse
import sys


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rosserial2-bridge", description=__doc__)
    p.add_argument("--transport", default="serial", choices=["serial"])
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=921600)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        import rclpy  # type: ignore[import-not-found]
    except ImportError:
        print(
            "rclpy is not installed; the bridge node cannot run.\n"
            "Install ROS2 (Humble or newer) and source its setup.bash.",
            file=sys.stderr,
        )
        return 2

    from rosserial2.session import Session  # noqa: F401  (used in M3)
    from rosserial2.transports.serial import SerialTransport  # noqa: F401

    rclpy.init()
    print(f"rosserial2-bridge: transport={args.transport} port={args.port} baud={args.baud}")
    print("M1 skeleton: real I/O loop lands in M3.")
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
