"""HIL smoke test: drive the bridge against real ESP32-S3 hardware.

Runs only on the self-hosted HIL runner. Connects to the device,
expects HELLO within a timeout, expects an ADVERTISE of the
``counter`` Int32 topic, then expects N data frames with monotonically
increasing payload values.

Exit codes:
    0 — smoke passed
    1 — smoke failed
    2 — could not open transport
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

from rosserial2.bridge import BridgeLoop
from rosserial2.transports.serial import SerialTransport


@dataclass
class _Recorder:
    type_str: str
    name: str
    published: list[object] = field(default_factory=list)

    def publish(self, value: object) -> None:
        self.published.append(value)


@dataclass
class _Factory:
    created: list[_Recorder] = field(default_factory=list)

    def __call__(self, type_str: str, name: str) -> _Recorder:
        rec = _Recorder(type_str, name)
        self.created.append(rec)
        return rec


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--expect", type=int, default=3,
                   help="number of counter values to observe before declaring success")
    p.add_argument("--timeout", type=float, default=15.0)
    args = p.parse_args()

    try:
        transport = SerialTransport(port=args.port, baud=args.baud)
    except Exception as exc:
        print(f"open failed: {exc}", file=sys.stderr)
        return 2

    factory = _Factory()
    loop = BridgeLoop(transport=transport, publisher_factory=factory)

    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline:
            loop.run_once()
            if factory.created:
                rec = factory.created[0]
                if (
                    rec.type_str == "std_msgs/msg/Int32"
                    and rec.name == "counter"
                    and len(rec.published) >= args.expect
                ):
                    values = rec.published[: args.expect]
                    if all(isinstance(v, int) for v in values) and values == sorted(values):
                        print(f"HIL OK: counter values {values}")
                        return 0
        print(
            "HIL FAIL: timed out without observing expected publishes; "
            f"factory.created={factory.created!r}",
            file=sys.stderr,
        )
        return 1
    finally:
        loop.stop()
        transport.close()


if __name__ == "__main__":
    raise SystemExit(main())
